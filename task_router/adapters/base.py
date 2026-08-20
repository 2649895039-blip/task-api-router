"""所有 provider 适配器的统一接口"""
from abc import ABC, abstractmethod
from typing import Iterator, List, Optional

from ..models import ModelConfig, ModelResponse


class BaseAdapter(ABC):
    """新增一个 provider：继承本类并实现 chat() 即可。

    messages 统一为 OpenAI 风格：
        [{"role": "system"|"user"|"assistant", "content": "..."}]
    """

    @abstractmethod
    def chat(
        self,
        model_cfg: ModelConfig,
        messages: List[dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> ModelResponse:
        """调用上游模型，返回统一的 ModelResponse。"""

    @abstractmethod
    def stream(
        self,
        model_cfg: ModelConfig,
        messages: List[dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Iterator[str]:
        """调用上游模型流式输出，逐个 yield 文本增量（不含 usage，由网关格式化为 SSE）。"""