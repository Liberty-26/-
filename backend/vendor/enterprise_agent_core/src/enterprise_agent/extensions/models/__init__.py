"""Provider-neutral model adapters."""

from enterprise_agent.extensions.models.base import ModelAdapter, ModelAdapterError
from enterprise_agent.extensions.models.factory import build_model_adapter
from enterprise_agent.extensions.models.fake import FakeModelAdapter
from enterprise_agent.extensions.models.openai_compatible import (
    ModelConfigurationError,
    OpenAICompatibleAdapter,
)

__all__ = [
    "FakeModelAdapter",
    "ModelAdapter",
    "ModelAdapterError",
    "ModelConfigurationError",
    "OpenAICompatibleAdapter",
    "build_model_adapter",
]
