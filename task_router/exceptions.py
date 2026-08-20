"""自定义异常"""
class TaskApiRouterError(Exception):
    """基础异常"""

class ModelNotFoundError(TaskApiRouterError):
    def __init__(self, model_id):
        self.model_id = model_id
        super().__init__(f"模型 [{model_id}] 未在注册表中找到")

class ModelNotConfiguredError(TaskApiRouterError):
    def __init__(self, model_id, missing):
        self.model_id = model_id
        self.missing = missing
        super().__init__(f"模型 [{model_id}] 配置不完整，缺少: {missing}")

class ProviderCallError(TaskApiRouterError):
    """调用上游 API 失败"""