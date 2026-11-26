"""Query Embedding 与主 Embedding 配置的一致性（Qwen3-VL 分支）。

覆盖：VL 端点强制继承、独立 Key 覆盖、主 Key 回退、缺少 Key 报错，
以及普通文本 Embedding 模型的行为保持不变。
"""

from __future__ import annotations

import pytest
from zleap.sag.core.adapters.defaults import OpenAIEmbeddingAdapter

from sag_api.core.chatbot_config import EmbeddingConnection, Environment, LLMConnection
from sag_api.core.config import Settings
from sag_api.core.errors import ConfigurationError
from sag_api.sag.multimodal_embedding import DashScopeMultimodalEmbeddingAdapter
from sag_api.services import chatbot_service as rt

NATIVE_ENDPOINT = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"
)
LEGACY_QUERY_ENDPOINT = "https://legacy.example.com/compatible-mode/v1"


def build_settings(**overrides) -> Settings:
    values: dict[str, object] = {
        "embedding_model": "qwen3-vl-embedding",
        "embedding_api_key": "sk-main",
        "embedding_base_url": "",
        "embedding_schema_dimensions": 1024,
        "embedding_request_dimensions": 1024,
        "embedding_multimodal_endpoint": NATIVE_ENDPOINT,
        "embedding_multimodal_dimension": 1024,
    }
    values.update(overrides)
    return Settings(**values)


def build_snapshot(
    settings: Settings,
    *,
    base_url: str = LEGACY_QUERY_ENDPOINT,
    api_key: str = "sk-query",
    enabled: bool = True,
) -> rt.Snapshot:
    connection = EmbeddingConnection(enabled=enabled, base_url=base_url, api_key=api_key)
    return rt.Snapshot(Environment(env={}), settings, {"llm": LLMConnection(), "embedding": connection})


async def _close(adapter: object) -> None:
    closer = getattr(adapter, "close", None)
    if closer is not None:
        await closer()


async def test_vl_query_endpoint_inherits_native_endpoint():
    """查询连接填了 OpenAI 兼容地址，也必须落到原生端点。"""
    snapshot = build_snapshot(build_settings())

    adapter = snapshot.adapter("embedding")

    try:
        assert isinstance(adapter, DashScopeMultimodalEmbeddingAdapter)
        assert adapter.endpoint == NATIVE_ENDPOINT
        assert adapter.config.base_url == NATIVE_ENDPOINT
    finally:
        await _close(adapter)


async def test_vl_query_uses_separate_key_when_provided():
    snapshot = build_snapshot(build_settings(), api_key="sk-query")

    adapter = snapshot.adapter("embedding")

    try:
        assert isinstance(adapter, DashScopeMultimodalEmbeddingAdapter)
        assert adapter.config.api_key == "sk-query"
    finally:
        await _close(adapter)


async def test_vl_query_falls_back_to_main_embedding_key():
    snapshot = build_snapshot(build_settings(), api_key="")

    adapter = snapshot.adapter("embedding")

    try:
        assert isinstance(adapter, DashScopeMultimodalEmbeddingAdapter)
        assert adapter.config.api_key == "sk-main"
    finally:
        await _close(adapter)


async def test_vl_query_requires_a_key_from_somewhere():
    snapshot = build_snapshot(build_settings(embedding_api_key=None), api_key="")

    with pytest.raises(ConfigurationError) as excinfo:
        snapshot.adapter("embedding")

    message = str(excinfo.value)
    assert "Qwen3-VL" in message
    assert "API key" in message


async def test_text_embedding_query_connection_keeps_own_endpoint_and_key():
    """普通文本模型：查询连接仍可独立指定端点与 Key（行为不变）。"""
    settings = build_settings(
        embedding_model="qwen3.7-text-embedding-flash",
        embedding_api_key="sk-main",
        embedding_base_url="https://main.example.com/v1",
        embedding_multimodal_endpoint=None,
        embedding_multimodal_dimension=None,
    )
    snapshot = build_snapshot(settings, base_url=LEGACY_QUERY_ENDPOINT, api_key="sk-query")

    adapter = snapshot.adapter("embedding")

    try:
        assert isinstance(adapter, OpenAIEmbeddingAdapter)
        assert adapter._config.base_url == LEGACY_QUERY_ENDPOINT
        assert adapter._config.api_key == "sk-query"
    finally:
        await _close(adapter)


async def test_text_embedding_query_connection_without_key_stays_keyless():
    """普通文本模型：没给查询 Key 时仍走原有无鉴权适配器（行为不变）。"""
    settings = build_settings(
        embedding_model="qwen3.7-text-embedding-flash",
        embedding_api_key="sk-main",
        embedding_base_url="https://main.example.com/v1",
        embedding_multimodal_endpoint=None,
        embedding_multimodal_dimension=None,
    )
    snapshot = build_snapshot(settings, base_url=LEGACY_QUERY_ENDPOINT, api_key="")

    adapter = snapshot.adapter("embedding")

    assert isinstance(adapter, rt.KeylessEmbeddingAdapter)
    assert adapter.config.base_url == LEGACY_QUERY_ENDPOINT
