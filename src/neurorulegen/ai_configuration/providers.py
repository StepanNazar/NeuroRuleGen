"""AI Provider registry and factory abstractions for LangChain integration."""

from abc import ABC, abstractmethod
from typing import Any

from langchain_azure_ai.chat_models import AzureAIOpenAIApiChatModel


class AIProviderAdapter(ABC):
    """Abstract adapter for creating chat models from an AI provider."""

    @abstractmethod
    def create_chat_model(
        self,
        model_identifier: str,
        api_key: str,
        config: dict[str, Any] | None = None,
    ) -> Any:
        """Instantiate and return a LangChain BaseChatModel."""
        pass


class AzureAIFoundryAdapter(AIProviderAdapter):
    """Adapter for Azure AI Foundry models using langchain-azure-ai or langchain-openai."""

    def create_chat_model(
        self,
        model_identifier: str,
        api_key: str,
        config: dict[str, Any] | None = None,
    ) -> Any:
        cfg = config or {}
        endpoint = cfg.get("endpoint") or cfg.get("base_url")
        project_endpoint = cfg.get("project_endpoint")

        kwargs: dict[str, Any] = {
            "model": model_identifier,
            "credential": api_key,
        }
        if project_endpoint:
            kwargs["project_endpoint"] = project_endpoint
        if endpoint:
            kwargs["endpoint"] = endpoint
        return AzureAIOpenAIApiChatModel(**kwargs)


class AIProviderRegistry:
    """Registry allowing easy registration and instantiation of LLM providers."""

    _adapters: dict[str, AIProviderAdapter] = {
        "azure_ai_foundry": AzureAIFoundryAdapter(),
        "azure_foundry": AzureAIFoundryAdapter(),
    }

    @classmethod
    def register_provider(cls, name: str, adapter: AIProviderAdapter) -> None:
        cls._adapters[name] = adapter

    @classmethod
    def get_adapter(cls, name: str) -> AIProviderAdapter:
        if name not in cls._adapters:
            raise ValueError(
                f"Unsupported AI provider '{name}'. Registered: {list(cls._adapters.keys())}"
            )
        return cls._adapters[name]

    @classmethod
    def create_chat_model(
        cls,
        provider_name: str,
        model_identifier: str,
        api_key: str,
        config: dict[str, Any] | None = None,
    ) -> Any:
        adapter = cls.get_adapter(provider_name)
        return adapter.create_chat_model(
            model_identifier=model_identifier,
            api_key=api_key,
            config=config,
        )
