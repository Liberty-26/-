"""Build a model adapter from secret-free Package settings."""

from __future__ import annotations

from enterprise_agent.contracts import ModelSettings
from enterprise_agent.extensions.models.base import ModelAdapter
from enterprise_agent.extensions.models.fake import FakeModelAdapter
from enterprise_agent.extensions.models.openai_compatible import OpenAICompatibleAdapter


def build_model_adapter(settings: ModelSettings) -> ModelAdapter:
    if settings.provider == "fake":
        return FakeModelAdapter(model=settings.model)
    if settings.provider == "openai_compatible":
        return OpenAICompatibleAdapter(settings)
    raise ValueError(f"Unsupported model provider: {settings.provider}")
