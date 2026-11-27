"""Construct the concrete embedding client inside SAG's existing scoped registry factory."""

from zleap.sag.config import EmbeddingConfig
from zleap.sag.core.adapters import defaults

from sag_api.core.embedding_policy import is_multimodal_embedding_model
from sag_api.sag.multimodal_embedding import DashScopeMultimodalEmbeddingAdapter


def create_embedding(*, config: EmbeddingConfig):
    if is_multimodal_embedding_model(config.model):
        return DashScopeMultimodalEmbeddingAdapter(config, endpoint=config.base_url)
    return defaults.OpenAIEmbeddingAdapter(config=config)
