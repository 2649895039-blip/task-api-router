"""task-api-router: 任务级 AI 模型调度器（路由核心与具体模型/provider 解耦）"""
import logging

__version__ = "0.2.1"

# 库默认不打印日志：宿主可自行配置 logger；CLI 入口会 basicConfig 打开 WARNING 级别。
logging.getLogger(__name__).addHandler(logging.NullHandler())
