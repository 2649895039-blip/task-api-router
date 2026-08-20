"""适配器注册表：新增 provider = 写一个 adapter 并注册到这里"""
from .base import BaseAdapter
from .openai_compat import OpenAICompatAdapter
from .anthropic import AnthropicAdapter

ADAPTER_REGISTRY = {
    "openai_compat": OpenAICompatAdapter,
    "anthropic": AnthropicAdapter,
}