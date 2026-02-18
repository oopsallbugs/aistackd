"""Compatibility facade for the LLM client module."""

from ai_stack.llama.client import LLMClient, LLMResponse, create_client, quick_chat

__all__ = ["LLMClient", "LLMResponse", "create_client", "quick_chat"]
