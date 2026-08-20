"""数据模型：ModelConfig（注册表条目）与 ModelResponse（统一返回结构）"""
import os
from dataclasses import dataclass, field
from typing import List, Optional


def safe_error_text(exc: BaseException) -> str:
    """把异常转成可落盘的简短文本：只留类型 + HTTP 状态码。

    商用安全要求：SDK 异常 str 可能带请求 URL / header / key 片段，
    Reporter/RunLog 会把它写进 history.jsonl 和运行日志，绝不能原样透传。
    """
    code = getattr(exc, "status_code", None)
    suffix = f" [HTTP {code}]" if code else ""
    return f"{type(exc).__name__}{suffix}"


@dataclass
class ModelConfig:
    """单个模型的注册表配置。id 是路由层唯一标识，与具体 provider 解耦。

    api_format 决定走哪个 adapter：
      - openai_compat : OpenAI 兼容（DeepSeek/通义/GLM/Moonshot/Groq/OpenAI 本体等）
      - anthropic     : Claude
      - gemini        : Google（规划中）
    """
    id: str
    api_format: str = "openai_compat"
    base_url: str = ""
    api_key_env: str = ""                  # 优先从环境变量读 key
    api_key_envs: List[str] = field(default_factory=list)  # 可兼容多个本地变量名
    api_key: str = ""                      # 本地调试兜底（GitHub 上勿提交）
    upstream_model: str = ""               # 发给上游的实际模型名，默认等于 id
    capabilities: List[str] = field(default_factory=list)   # code/reasoning/bulk/translation/...
    cost_per_1k_in: float = 0.0            # 美元 / 每千 input token
    cost_per_1k_out: float = 0.0           # 美元 / 每千 output token
    speed: str = "medium"                  # fast/medium/slow
    quality: str = "medium"                # high/medium/low
    max_tokens: int = 4096
    timeout: float = 60.0                  # 上游请求超时秒数（防不可达模型长时间挂起）
    proxy: str = ""                        # 上游 http(s) 代理，如 http://127.0.0.1:7890

    def resolved_upstream_model(self) -> str:
        return self.upstream_model or self.id

    def resolved_api_key(self) -> Optional[str]:
        """优先环境变量，其次配置里的 api_key（本地兜底）"""
        env_names = list(self.api_key_envs)
        if self.api_key_env and self.api_key_env not in env_names:
            env_names.insert(0, self.api_key_env)
        for env_name in env_names:
            key = os.environ.get(env_name, "")
            if key:
                return key
        return self.api_key or None

    def missing_config(self) -> List[str]:
        """返回缺失的必填项（用于校验）"""
        missing = []
        if not self.base_url:
            missing.append("base_url")
        if not self.resolved_api_key():
            names = self.api_key_envs or ([self.api_key_env] if self.api_key_env else [])
            missing.append(f"api_key(设置 {' 或 '.join(names) or 'api_key'})")
        return missing

@dataclass
class ModelResponse:
    """一次模型调用的统一返回结构。所有 adapter 都返回它，上层逻辑不关心具体 provider。"""
    model_id: str
    content: str = ""
    reasoning_content: str = ""            # DeepSeek 等模型的思考内容（可选）
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cost: float = 0.0
    success: bool = True
    error: str = ""

    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @classmethod
    def fail(cls, model_id: str, error: str) -> "ModelResponse":
        return cls(model_id=model_id, success=False, error=error)
