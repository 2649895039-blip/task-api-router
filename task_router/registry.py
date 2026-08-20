"""模型注册表：从 YAML 加载任意数量模型，路由核心与 provider 完全解耦"""
import os
from typing import Any, List
import yaml

from .exceptions import ModelNotFoundError
import logging

log = logging.getLogger(__name__)

from .models import ModelConfig


class ModelRegistry:
    """模型注册表。

    用法：
        registry = ModelRegistry("config/models.yaml")
        registry.list()                 # 所有 model_id
        registry.get("deepseek-v4")     # ModelConfig
        registry.defaults               # 全局默认配置（如 planner_model）
    """

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.defaults: dict = {}
        self._models: dict = {}
        self._load()

    def _load(self):
        path = self.config_path
        # 商用发布：models.yaml 是本地私有文件（可能含真实 key，已在 .gitignore），
        # 新 clone 没有它时自动回退到公开模板 models.example.yaml，保证开箱即用。
        if not os.path.exists(path) and path.endswith(".yaml"):
            alt = path[:-5] + ".example.yaml"
            if os.path.exists(alt):
                log.warning(f"[提示] 未找到 {path}，使用模板 {alt}")
                path = alt
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        self.defaults = raw.get("defaults") or {}
        for model_id, cfg in (raw.get("models") or {}).items():
            self._models[model_id] = ModelConfig(id=model_id, **cfg)

    def default(self, key: str, fallback: Any = None) -> Any:
        return self.defaults.get(key, fallback)

    def get(self, model_id: str) -> ModelConfig:
        if model_id not in self._models:
            raise ModelNotFoundError(model_id)
        return self._models[model_id]

    def list(self) -> List[str]:
        return list(self._models.keys())

    def has(self, model_id: str) -> bool:
        return model_id in self._models

    def by_capability(self, capability: str) -> List[ModelConfig]:
        return [c for c in self._models.values() if capability in c.capabilities]

    def configured(self, model_id: str) -> bool:
        """模型配置是否完整（base_url + api_key 齐备）"""
        cfg = self.get(model_id)
        return not cfg.missing_config()