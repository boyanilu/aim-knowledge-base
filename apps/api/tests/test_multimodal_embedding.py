"""多模态 Embedding 适配器测试（不访问真实网络，全部走 httpx MockTransport）。"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from zleap.sag.config import EmbeddingConfig
from zleap.sag.core.adapters import defaults
from zleap.sag.exceptions import AIAuthError, AIInvalidRequestError

from sag_api.core.embedding_policy import is_multimodal_embedding_model
from sag_api.sag import embedding_factory
from sag_api.sag.multimodal_embedding import (
    DASHSCOPE_MULTIMODAL_ENDPOINT,
    DashScopeMultimodalEmbeddingAdapter,
)


def _config(model: str = "qwen3-vl-embedding", dimensions: int | None = 4) -> EmbeddingConfig:
    return EmbeddingConfig(
        model=model,
        api_key="sk-test",
        base_url="https://example.invalid/compatible-mode/v1",
        schema_dimensions=dimensions,
        request_dimensions=dimensions,
        timeout=10,
    )


def _adapter(handler, *, dimensions: int | None = 4) -> DashScopeMultimodalEmbeddingAdapter:
    return DashScopeMultimodalEmbeddingAdapter(
        _config(dimensions=dimensions),
        transport=httpx.MockTransport(handler),
    )


def _vectors(count: int, dim: int = 4) -> list[dict[str, object]]:
    return [
        {"index": index, "embedding": [float(index) + 0.1 * (i + 1) for i in range(dim)]}
        for index in range(count)
    ]


def _ok(contents: list[dict[str, object]], *, fusion: bool = False) -> httpx.Response:
    count = 1 if fusion else len(contents)
    return httpx.Response(200, json={"output": {"embeddings": _vectors(count)}})


def test_is_multimodal_embedding_model():
    assert is_multimodal_embedding_model("qwen3-vl-embedding")
    assert is_multimodal_embedding_model("Qwen3-VL-Embedding")
    assert not is_multimodal_embedding_model("qwen3.7-text-embedding-flash")
    assert not is_multimodal_embedding_model(None)


def test_batch_generate_returns_independent_vectors_in_order():
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append(body)
        assert request.url == httpx.URL(DASHSCOPE_MULTIMODAL_ENDPOINT)
        return _ok(body["input"]["contents"])

    async def run():
        adapter = _adapter(handler)
        try:
            return await adapter.batch_generate(["第一段", "第二段", "第三段"])
        finally:
            await adapter.close()

    vectors = asyncio.run(run())

    assert len(vectors) == 3
    # 每条文本必须是独立的 content，绝不能被合并成一个融合请求
    assert [item["text"] for item in captured[0]["input"]["contents"]] == ["第一段", "第二段", "第三段"]
    assert "enable_fusion" not in captured[0].get("parameters", {})
    assert vectors[0][0] == pytest.approx(0.1)


def test_batch_generate_splits_at_content_limit():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(len(body["input"]["contents"]))
        return _ok(body["input"]["contents"])

    async def run():
        adapter = _adapter(handler)
        try:
            return await adapter.batch_generate([f"t{i}" for i in range(45)])
        finally:
            await adapter.close()

    vectors = asyncio.run(run())

    assert len(vectors) == 45
    assert calls == [20, 20, 5]


def test_generate_single_text():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return _ok(body["input"]["contents"])

    async def run():
        adapter = _adapter(handler)
        try:
            return await adapter.generate("单条文本")
        finally:
            await adapter.close()

    vector = asyncio.run(run())
    assert len(vector) == 4


def test_embed_image_accepts_base64_payload():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.update(body)
        return httpx.Response(200, json={"output": {"embeddings": _vectors(1)}})

    async def run():
        adapter = _adapter(handler)
        try:
            return await adapter.embed_image("data:image/png;base64,AAAA")
        finally:
            await adapter.close()

    vector = asyncio.run(run())
    assert len(vector) == 4
    assert seen["input"]["contents"][0]["image"] == "data:image/png;base64,AAAA"


def test_embed_multimodal_fusion_sends_flag_and_returns_single_vector():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.update(body)
        return httpx.Response(200, json={"output": {"embeddings": _vectors(1)}})

    async def run():
        adapter = _adapter(handler)
        try:
            return await adapter.embed_multimodal(
                [{"text": "结构设计"}, {"image": "https://example.invalid/a.png"}]
            )
        finally:
            await adapter.close()

    vector = asyncio.run(run())
    assert len(vector) == 4
    assert seen["parameters"]["enable_fusion"] is True


def test_dimension_mismatch_raises_clear_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"output": {"embeddings": [{"index": 0, "embedding": [0.1] * 8}]}},
        )

    async def run():
        adapter = _adapter(handler, dimensions=4)
        try:
            await adapter.generate("文本")
        finally:
            await adapter.close()

    with pytest.raises(AIInvalidRequestError) as excinfo:
        asyncio.run(run())
    assert "维度不一致" in str(excinfo.value)


def test_auth_error_is_mapped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": "InvalidApiKey", "message": "bad key"})

    async def run():
        adapter = _adapter(handler)
        try:
            await adapter.generate("文本")
        finally:
            await adapter.close()

    with pytest.raises(AIAuthError):
        asyncio.run(run())


def test_returned_count_mismatch_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output": {"embeddings": _vectors(1)}})

    async def run():
        adapter = _adapter(handler)
        try:
            await adapter.batch_generate(["a", "b"])
        finally:
            await adapter.close()

    with pytest.raises(AIInvalidRequestError) as excinfo:
        asyncio.run(run())
    assert "数量与输入不一致" in str(excinfo.value)


def test_reuse_identity_and_prepared_input():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - 不发起请求
        return httpx.Response(200, json={"output": {"embeddings": _vectors(1)}})

    adapter = _adapter(handler)
    identity = adapter.reuse_identity()

    assert identity.provider == "dashscope-multimodal"
    assert identity.model == "qwen3-vl-embedding"
    assert identity.endpoint.startswith("https://dashscope.aliyuncs.com/")
    assert "multimodal" in identity.output_options_json

    prepared = adapter.prepare_input("待向量化文本")
    assert prepared.wire_text == "待向量化文本"
    assert prepared.model_identity == identity


def test_factory_routes_vl_model_and_keeps_text_model_default():
    factory = embedding_factory.create_embedding

    vl = factory(config=_config("qwen3-vl-embedding"))
    assert isinstance(vl, DashScopeMultimodalEmbeddingAdapter)

    text = factory(config=_config("qwen3.7-text-embedding-flash"))
    assert isinstance(text, defaults.OpenAIEmbeddingAdapter)


@pytest.mark.parametrize("indices", [[0, 0], [1, 2]])
async def test_rejects_ambiguous_indices(indices):
    rows = [{"index": index, "embedding": [1.0] * 4} for index in indices]
    async with _adapter(lambda req: httpx.Response(200, json={"output": {"embeddings": rows}})) as adapter:
        with pytest.raises(AIInvalidRequestError, match="indices"):
            await adapter.batch_generate(["a", "b"])


async def test_fusion_limit_and_instruction():
    def handler(request):
        assert json.loads(request.content)["parameters"]["instruct"] == "Describe this image"
        return _ok([{}])

    async with _adapter(handler) as adapter:
        await adapter.embed_image("https://example.invalid/image", instruction="Describe this image")
        with pytest.raises(AIInvalidRequestError):
            await adapter.embed_multimodal([{"text": "x"}] * 21)


def test_vl_native_endpoint_and_independent_credentials():
    from sag_api.core.config import Settings
    from sag_api.sag.config_builder import build_engine_config

    settings = Settings(_env_file=None, embedding_model="qwen3-vl-embedding", llm_api_key="llm-only",
                        embedding_api_key=None, embedding_multimodal_endpoint="https://native.invalid/embed")
    config = build_engine_config(settings).embedding
    assert settings.effective_embedding_api_key is None
    assert config.base_url == "https://native.invalid/embed"
    assert config.schema_dimensions == config.request_dimensions == 1024
    with pytest.raises(AIInvalidRequestError, match="dimension"):
        DashScopeMultimodalEmbeddingAdapter(config, dimension=2560)


async def test_registry_and_optional_query_client_preserve_scoped_routing():
    from zleap.sag.core.adapters import registry

    from sag_api.core.chatbot_config import EmbeddingConnection, Environment
    from sag_api.core.config import Settings
    from sag_api.sag.config_builder import build_engine_config
    from sag_api.services.chatbot_service import ScopedAdapter, Snapshot, install_query_adapters

    settings = Settings(_env_file=None, embedding_model="qwen3-vl-embedding", embedding_api_key="example")
    install_query_adapters()
    install_query_adapters()
    engine_client = registry.create_embedding(config=build_engine_config(settings).embedding)
    query_url = "https://query.invalid/native"
    connection = EmbeddingConnection(enabled=True, base_url=query_url, api_key="example")
    from sag_api.core.chatbot_config import LLMConnection

    snapshot = Snapshot(Environment({}), settings, {"embedding": connection, "llm": LLMConnection()})
    try:
        assert isinstance(engine_client, ScopedAdapter)
        assert isinstance(engine_client.original, DashScopeMultimodalEmbeddingAdapter)
        assert engine_client.reuse_identity().endpoint == DASHSCOPE_MULTIMODAL_ENDPOINT
        # VL 查询连接必须继承主配置的原生端点；连接自带的 base_url 不生效。
        query_adapter = snapshot.adapter("embedding")
        assert isinstance(query_adapter, DashScopeMultimodalEmbeddingAdapter)
        assert query_adapter.reuse_identity().endpoint == DASHSCOPE_MULTIMODAL_ENDPOINT
        assert query_adapter.config.base_url != query_url
    finally:
        await engine_client.close()
        await snapshot.close()
