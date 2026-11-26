"""DashScope 多模态 Embedding 适配器（Qwen3-VL-Embedding 等）。

背景：SAG 引擎默认的 ``OpenAIEmbeddingAdapter`` 只认 OpenAI 兼容的
``POST {base_url}/embeddings``，输入是 ``input: list[str]``。而阿里云百炼的多模态
向量模型走的是**独立的 DashScope 原生端点**：

    POST https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding
    {"model": "qwen3-vl-embedding",
     "input": {"contents": [{"text": "..."}, {"image": "url|base64"}]},
     "parameters": {"enable_fusion": true, "dimension": 2560}}

两种向量模式：
* 独立向量（默认）：每个 content 各自出一个向量，数量与 contents 一致；
* 融合向量（``enable_fusion=true``）：所有 content 合成一个向量。

本适配器实现引擎所需的 ``EmbeddingAdapter`` 协议（``generate`` / ``batch_generate``），
并额外提供 ``embed_image`` / ``embed_multimodal`` 供后续图片向量化模块复用。
文本batch 始终使用独立向量模式，绝不被合并成融合向量。
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Sequence
from typing import Any, NoReturn

import httpx
from zleap.sag.config import EmbeddingConfig
from zleap.sag.core.adapters.models import ModelReuseIdentity, PreparedEmbeddingInput
from zleap.sag.exceptions import AIAuthError, AIInvalidRequestError, AITransientError

from sag_api.core.embedding_policy import DASHSCOPE_MULTIMODAL_ENDPOINT

#: 单次请求的 content 元素上限（官方：元素总数 ≤ 20，图片 ≤ 10，视频 ≤ 1）。
MAX_CONTENT_ELEMENTS = 20
MAX_IMAGES_PER_REQUEST = 10

#: 错误响应里用于判定“可重试”的状态码。
_TRANSIENT_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


def _split_batches(items: Sequence[Any], size: int) -> list[list[Any]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


class DashScopeMultimodalEmbeddingAdapter:
    """把 DashScope 多模态向量接口适配成 SAG 的 EmbeddingAdapter。

    与默认适配器一样按构造参数注入配置，不做全局状态；实例自己持有 HTTP 客户端，
    由 ``close()`` 释放。
    """

    def __init__(
        self,
        config: EmbeddingConfig,
        *,
        endpoint: str | None = None,
        dimension: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if config is None:  # pragma: no cover - 与默认适配器一致的防御
            raise AIInvalidRequestError("多模态 Embedding 适配器需要显式注入 config")
        self.config = config
        # 显式传入的 endpoint 优先；否则用官方端点（base_url 是 OpenAI 兼容地址，不能复用）。
        self.endpoint = endpoint or DASHSCOPE_MULTIMODAL_ENDPOINT
        self.dimension = dimension if dimension is not None else config.request_dimensions
        if self.dimension is None:
            self.dimension = config.schema_dimensions
        if config.schema_dimensions and self.dimension != config.schema_dimensions:
            raise AIInvalidRequestError("VL request dimension must match the embedding schema dimension")
        self._client = httpx.AsyncClient(
            timeout=float(config.timeout or 60),
            transport=transport,
        )

    # ── 引擎协议 ────────────────────────────────────────────────
    async def generate(self, text: str) -> list[float]:
        """单条文本 → 一个向量。"""
        vectors = await self._request([{"text": text}], fusion=False)
        return vectors[0]

    async def batch_generate(self, texts: list[str]) -> list[list[float]]:
        """多条文本 → 多个独立向量，顺序与输入一致（绝不融合）。"""
        if not texts:
            return []
        vectors: list[list[float]] = []
        for batch in _split_batches(texts, MAX_CONTENT_ELEMENTS):
            vectors.extend(await self._request([{"text": t} for t in batch], fusion=False))
        return vectors

    # ── 多模态扩展（供后续图片向量化/跨模态检索复用）────────────────
    async def embed_image(self, image: str, *, instruction: str | None = None) -> list[float]:
        """单张图片（URL 或 base64/DataURL）→ 一个向量。"""
        vectors = await self._request([{"image": image}], fusion=False, instruction=instruction)
        return vectors[0]

    async def embed_multimodal(
        self,
        contents: Sequence[dict[str, Any]],
        *,
        fusion: bool = True,
        instruction: str | None = None,
    ) -> list[float] | list[list[float]]:
        """图文混合 → 融合向量（默认）或逐项独立向量。"""
        items = [dict(item) for item in contents]
        vectors = await self._request(items, fusion=fusion, instruction=instruction)
        return vectors[0] if fusion else vectors

    async def close(self) -> None:
        await self._client.aclose()

    # ── 可选语义协议（引擎在入库去重/缓存时会调用）──────────────────
    def reuse_identity(self) -> ModelReuseIdentity:
        """向量空间身份：模型 + 端点 + 维度。

        引擎用它判断“同一段文本能否复用已算好的向量”。多模态模型与纯文本模型
        的指纹必须不同，避免跨模型复用向量。
        """
        return ModelReuseIdentity(
            provider="dashscope-multimodal",
            endpoint=self.endpoint,
            model=self.config.model,
            output_options_json=json.dumps(
                {"dimension": self.dimension, "family": "multimodal"},
                sort_keys=True,
            ),
            formatter_version="multimodal-v1",
        )

    def prepare_input(self, text: str) -> PreparedEmbeddingInput:
        return PreparedEmbeddingInput(wire_text=text, model_identity=self.reuse_identity())

    # ── 内部实现 ────────────────────────────────────────────────
    async def _request(
        self, contents: list[dict[str, Any]], *, fusion: bool, instruction: str | None = None
    ) -> list[list[float]]:
        if not contents:
            raise AIInvalidRequestError("多模态 Embedding 请求内容为空")
        image_count = sum(1 for item in contents if "image" in item)
        if sum("video" in item for item in contents) > 1:
            raise AIInvalidRequestError("A request supports at most one video")
        if image_count > MAX_IMAGES_PER_REQUEST:
            raise AIInvalidRequestError(
                f"单次请求图片数量超限：{image_count} > {MAX_IMAGES_PER_REQUEST}"
            )
        if len(contents) > MAX_CONTENT_ELEMENTS:
            raise AIInvalidRequestError(
                f"单次请求元素数量超限：{len(contents)} > {MAX_CONTENT_ELEMENTS}"
            )

        payload: dict[str, Any] = {
            "model": self.config.model,
            "input": {"contents": contents},
        }
        parameters: dict[str, Any] = {}
        if instruction:
            parameters["instruct"] = instruction
        if fusion:
            parameters["enable_fusion"] = True
        if self.dimension:
            parameters["dimension"] = int(self.dimension)
        if parameters:
            payload["parameters"] = parameters

        for attempt in range(self.config.max_retries + 1):
            try:
                response = await self._post(payload)
                break
            except AITransientError:
                if attempt == self.config.max_retries:
                    raise
                await asyncio.sleep(min(2**attempt, 8))
        vectors = self._parse_vectors(response)
        expected = 1 if fusion else len(contents)
        if len(vectors) != expected:
            self._fail_count(expected, len(vectors))
        return vectors

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            response = await self._client.post(
                self.endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.config.api_key or ''}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.TimeoutException as exc:
            raise AITransientError("多模态 Embedding 请求超时", details={"failure_kind": "timeout"}) from exc
        except httpx.HTTPError as exc:
            raise AITransientError(f"多模态 Embedding 请求失败：{type(exc).__name__}") from exc

        if response.status_code >= 400:
            self._raise_for_status(response)
        return response

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status in (401, 403):
            raise AIAuthError(f"多模态 Embedding 认证失败（HTTP {status}）")
        if status in _TRANSIENT_STATUS:
            raise AITransientError(f"多模态 Embedding 服务暂时不可用（HTTP {status}）")
        raise AIInvalidRequestError(f"多模态 Embedding 请求被拒绝（HTTP {status}）")

    def _parse_vectors(self, response: httpx.Response) -> list[list[float]]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise AIInvalidRequestError("多模态 Embedding 返回的不是合法 JSON") from exc

        output = payload.get("output") if isinstance(payload, dict) else None
        entries = output.get("embeddings") if isinstance(output, dict) else None
        if not isinstance(entries, list) or not all(isinstance(row, dict) for row in entries):
            raise AIInvalidRequestError("Invalid DashScope embedding response")
        if any("index" in row for row in entries):
            indices = [row.get("index") for row in entries]
            if not all(type(i) is int for i in indices) or sorted(indices) != list(range(len(entries))):
                raise AIInvalidRequestError("Invalid DashScope embedding indices")
            entries = sorted(entries, key=lambda row: row["index"])

        vectors: list[list[float]] = []
        for row in entries:
            item = row.get("embedding")
            if not isinstance(item, list) or not item or any(type(v) not in (float, int) for v in item):
                raise AIInvalidRequestError("Invalid embedding values")
            try:
                vector = [float(value) for value in item]
            except (TypeError, ValueError) as exc:
                raise AIInvalidRequestError("多模态 Embedding 返回的向量元素不是数字") from exc
            if not all(math.isfinite(v) for v in vector):
                raise AIInvalidRequestError("Non-finite embedding vector")
            self._validate_dimensions(vector)
            vectors.append(vector)
        if not vectors:
            raise AIInvalidRequestError("多模态 Embedding 返回中没有可用向量")
        return vectors

    def _validate_dimensions(self, vector: list[float]) -> None:
        expected = self.config.schema_dimensions
        if expected and len(vector) != expected:
            raise AIInvalidRequestError(
                f"多模态 Embedding 维度不一致：模型返回 {len(vector)} 维，配置要求 {expected} 维；"
                "请修改 SAG_EMBEDDING_SCHEMA_DIMENSIONS 与请求维度后重建索引"
            )

    @staticmethod
    def _fail_count(expected: int, actual: int) -> NoReturn:
        raise AIInvalidRequestError(
            f"多模态 Embedding 返回数量与输入不一致：期望 {expected} 个向量，实际 {actual} 个"
        )

    async def __aenter__(self) -> DashScopeMultimodalEmbeddingAdapter:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()
