"""Anthropic 格式适配器（Claude）。

Anthropic 的消息格式与 OpenAI 不同（system 独立、内容块、需要 x-api-key 头），
所以单独一个 adapter。用官方 anthropic SDK。
"""
import time
from typing import List, Optional

from ..exceptions import ProviderCallError
from ..models import ModelConfig, ModelResponse, safe_error_text
from .base import BaseAdapter
from .openai_compat import make_http_client


class AnthropicAdapter(BaseAdapter):
    def chat(
        self,
        model_cfg: ModelConfig,
        messages: List[dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> ModelResponse:
        missing = model_cfg.missing_config()
        if missing:
            return ModelResponse.fail(model_cfg.id, f"配置不完整: {missing}")

        from anthropic import Anthropic

        client = Anthropic(
            api_key=model_cfg.resolved_api_key(),
            base_url=model_cfg.base_url or None,
            http_client=make_http_client(model_cfg),
        )

        # OpenAI 风格消息 → Anthropic 风格（system 拆出来）
        system_parts = []
        msgs = []
        for m in messages:
            role = m.get("role")
            content = str(m.get("content", ""))
            if role == "system":
                system_parts.append(content)
            elif role in ("user", "assistant"):
                msgs.append({"role": role, "content": content})
        if not msgs:
            msgs = [{"role": "user", "content": "hi"}]

        kwargs: dict = {
            "model": model_cfg.resolved_upstream_model(),
            "messages": msgs,
            "max_tokens": max_tokens if max_tokens is not None else model_cfg.max_tokens,
        }
        if system_parts:
            kwargs["system"] = "\n".join(system_parts)
        if temperature is not None:
            kwargs["temperature"] = temperature

        start = time.time()
        try:
            try:
                resp = client.messages.create(**kwargs)
            except Exception as e:
                return ModelResponse.fail(model_cfg.id, f"调用失败: {safe_error_text(e)}")
        finally:
            client.close()   # 用完即关，防并发下连接/fd 泄漏
        latency_ms = int((time.time() - start) * 1000)

        content = "".join(b.text for b in resp.content if b.type == "text")
        in_tokens = resp.usage.input_tokens
        out_tokens = resp.usage.output_tokens
        cost = (
            in_tokens / 1000 * model_cfg.cost_per_1k_in
            + out_tokens / 1000 * model_cfg.cost_per_1k_out
        )

        return ModelResponse(
            model_id=model_cfg.id,
            content=content,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            latency_ms=latency_ms,
            cost=cost,
        )

    def stream(
        self,
        model_cfg: ModelConfig,
        messages: List[dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ):
        """流式版本：用 anthropic SDK 的消息流，逐个 yield 文本增量。"""
        from anthropic import Anthropic

        missing = model_cfg.missing_config()
        if missing:
            raise ValueError(f"配置不完整: {missing}")

        client = Anthropic(
            api_key=model_cfg.resolved_api_key(),
            base_url=model_cfg.base_url or None,
            http_client=make_http_client(model_cfg),
        )

        # OpenAI 风格消息 → Anthropic 风格（system 拆出来）
        system_parts = []
        msgs = []
        for m in messages:
            role = m.get("role")
            content = str(m.get("content", ""))
            if role == "system":
                system_parts.append(content)
            elif role in ("user", "assistant"):
                msgs.append({"role": role, "content": content})
        if not msgs:
            msgs = [{"role": "user", "content": "hi"}]

        kwargs: dict = {
            "model": model_cfg.resolved_upstream_model(),
            "messages": msgs,
            "max_tokens": max_tokens if max_tokens is not None else model_cfg.max_tokens,
        }
        if system_parts:
            kwargs["system"] = "\n".join(system_parts)
        if temperature is not None:
            kwargs["temperature"] = temperature

        try:
            try:
                with client.messages.stream(**kwargs) as stream:
                    for text in stream.text_stream:
                        yield text
            except GeneratorExit:
                raise
            except Exception as e:
                raise ProviderCallError(f"流式调用失败: {safe_error_text(e)}") from e
        finally:
            client.close()   # 调用方提前 break 丢弃生成器时也会关连接