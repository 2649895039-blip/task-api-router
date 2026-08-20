"""OpenAI 兼容适配器。

覆盖绝大多数 OpenAI 兼容 API：DeepSeek / 通义 / GLM / Moonshot / Groq / OpenAI 本体...
这些服务都实现了 OpenAI 的 /chat/completions 协议，只需 base_url + api_key。
"""
import time
from typing import List, Optional

import httpx
from openai import OpenAI

from ..exceptions import ProviderCallError
from ..models import ModelConfig, ModelResponse, safe_error_text
from .base import BaseAdapter


def make_http_client(model_cfg: ModelConfig) -> httpx.Client:
    """统一生成 httpx 客户端：timeout + 可选 proxy（国内访问被墙的上游需要）。"""
    return httpx.Client(timeout=model_cfg.timeout, proxy=model_cfg.proxy or None)


class OpenAICompatAdapter(BaseAdapter):
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

        client = OpenAI(
            api_key=model_cfg.resolved_api_key(),
            base_url=model_cfg.base_url,
            http_client=make_http_client(model_cfg),
        )
        kwargs: dict = {
            "model": model_cfg.resolved_upstream_model(),
            "messages": messages,
            "max_tokens": max_tokens if max_tokens is not None else model_cfg.max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature

        start = time.time()
        try:
            try:
                resp = client.chat.completions.create(**kwargs)
            except Exception as e:
                return ModelResponse.fail(model_cfg.id, f"调用失败: {safe_error_text(e)}")
        finally:
            client.close()   # 用完即关，防并发下连接/fd 泄漏
        latency_ms = int((time.time() - start) * 1000)

        # 上游异常/内容过滤可能返回空 choices，必须转成受控失败，不能抛 IndexError
        if not resp.choices:
            return ModelResponse.fail(model_cfg.id, "上游返回空 choices")
        msg = resp.choices[0].message
        content = msg.content or ""
        reasoning = getattr(msg, "reasoning_content", "") or ""
        # 思考模型可能 content 为空、只有 reasoning_content
        if not content and reasoning:
            content = reasoning
        usage = resp.usage
        in_tokens = usage.prompt_tokens if usage else 0
        out_tokens = usage.completion_tokens if usage else 0
        cost = (
            in_tokens / 1000 * model_cfg.cost_per_1k_in
            + out_tokens / 1000 * model_cfg.cost_per_1k_out
        )

        return ModelResponse(
            model_id=model_cfg.id,
            content=content,
            reasoning_content=reasoning,
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
        """流式版本：逐个 yield 文本增量。

        兼容支持 reasoning_content 的思考模型：也一并产出，
        与 chat() 的非流式合并逻辑保持一致。
        """
        missing = model_cfg.missing_config()
        if missing:
            raise ValueError(f"配置不完整: {missing}")

        client = OpenAI(
            api_key=model_cfg.resolved_api_key(),
            base_url=model_cfg.base_url,
            http_client=make_http_client(model_cfg),
        )
        kwargs: dict = {
            "model": model_cfg.resolved_upstream_model(),
            "messages": messages,
            "max_tokens": max_tokens if max_tokens is not None else model_cfg.max_tokens,
            "stream": True,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature

        try:
            try:
                stream = client.chat.completions.create(**kwargs)
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    piece = getattr(delta, "reasoning_content", None) or ""
                    if not piece:
                        piece = delta.content or ""
                    if piece:
                        yield piece
            except GeneratorExit:
                raise
            except Exception as e:
                raise ProviderCallError(f"流式调用失败: {safe_error_text(e)}") from e
        finally:
            client.close()   # 调用方提前 break 丢弃生成器时也会关连接