"""ModelClient：统一入口。上层只传 model_id，具体走哪个 adapter 由注册表决定。"""
from typing import List, Optional

from .adapters import ADAPTER_REGISTRY, BaseAdapter
from .models import ModelConfig, ModelResponse
from .registry import ModelRegistry


class ModelClient:
    def __init__(self, registry: ModelRegistry, adapter_registry: dict = None):
        self.registry = registry
        self._adapter_registry = adapter_registry or ADAPTER_REGISTRY
        self._adapters: dict = {}

    def _get_adapter(self, api_format: str) -> BaseAdapter:
        if api_format not in self._adapters:
            cls = self._adapter_registry.get(api_format)
            if cls is None:
                raise ValueError(f"不支持的 api_format: {api_format}")
            self._adapters[api_format] = cls()
        return self._adapters[api_format]

    def chat(self, model_id: str, messages: List[dict], **kwargs) -> ModelResponse:
        """按 model_id 调用对应模型。messages 为 OpenAI 风格消息列表。"""
        cfg = self.registry.get(model_id)
        adapter = self._get_adapter(cfg.api_format)
        return adapter.chat(cfg, messages, **kwargs)

    def stream(self, model_id: str, messages: List[dict], **kwargs):
        """流式调用对应模型，逐个 yield 文本增量。"""
        cfg = self.registry.get(model_id)
        adapter = self._get_adapter(cfg.api_format)
        yield from adapter.stream(cfg, messages, **kwargs)

    def list(self) -> List[str]:
        return self.registry.list()