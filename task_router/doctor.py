"""Install health check for onboarding friction — no API calls."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DoctorCheck:
    name: str
    ok: bool
    detail: str
    fix: str = ""


def run_doctor(config_path: str, data_dir: str, *, package_dir: str | None = None) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []

    version = sys.version_info
    py_ok = version >= (3, 10)
    checks.append(DoctorCheck(
        "python_version",
        py_ok,
        f"Python {version.major}.{version.minor}.{version.micro}",
        "" if py_ok else "需要 Python >= 3.10，请升级解释器",
    ))

    resolved_config = config_path
    config_exists = Path(config_path).is_file()
    if not config_exists and package_dir:
        packaged = Path(package_dir) / "config" / "models.example.yaml"
        if packaged.is_file():
            resolved_config = str(packaged)
            config_exists = True
    checks.append(DoctorCheck(
        "model_config",
        config_exists,
        resolved_config if config_exists else f"未找到 {config_path}",
        "" if config_exists else "复制 config/models.example.yaml 为 config/models.yaml 并填入模型",
    ))

    ready: list[str] = []
    try:
        from .registry import ModelRegistry
        registry = ModelRegistry(resolved_config)
        models = registry.list()
        ready = [mid for mid in models if registry.configured(mid)]
        missing = [mid for mid in models if mid not in ready]
        checks.append(DoctorCheck(
            "models_registered",
            bool(models),
            f"{len(models)} 个模型: {', '.join(models) or '(无)'}",
            "" if models else "在 models.yaml 的 models: 下至少配置一个模型",
        ))
        checks.append(DoctorCheck(
            "models_configured",
            bool(ready),
            f"{len(ready)} 个可用" + (f"，缺配置: {', '.join(missing)}" if missing else ""),
            "" if ready else "为至少一个模型设置 base_url 和 api_key 环境变量",
        ))
    except Exception as exc:
        checks.append(DoctorCheck(
            "model_config",
            False,
            f"配置无法加载: {type(exc).__name__}: {exc}",
            "检查 models.yaml YAML 语法与字段是否合法",
        ))

    ranking = Path(resolved_config).parent / "ranking.yaml"
    if not ranking.is_file() and package_dir:
        ranking = Path(package_dir) / "config" / "ranking.yaml"
    ranking_ok = ranking.is_file()
    checks.append(DoctorCheck(
        "ranking_table",
        ranking_ok,
        str(ranking) if ranking_ok else "未找到 ranking.yaml",
        "" if ranking_ok else "仓库应包含 config/ranking.yaml 路由月榜",
    ))

    data_path = Path(data_dir)
    try:
        data_path.mkdir(parents=True, exist_ok=True)
        probe = data_path / ".doctor_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        data_ok = True
        data_detail = f"可写: {data_path}"
    except OSError as exc:
        data_ok = False
        data_detail = f"数据目录不可写: {exc}"
    checks.append(DoctorCheck(
        "data_dir",
        data_ok,
        data_detail,
        "" if data_ok else "检查 data 目录权限或改用 --data 指定其他路径",
    ))

    if package_dir:
        install_root = Path(package_dir).parent
        repository_mode = (install_root / ".claude-plugin" / "plugin.json").is_file()
        hook = install_root / "hooks" / "action_guard_hook.py"
        hook_ok = hook.is_file() if repository_mode else True
        hook_detail = (
            str(hook) if hook.is_file()
            else "纯 pip 库安装不包含宿主 hook；核心 CLI 可正常使用"
            if not repository_mode
            else "插件仓库缺少 hooks/action_guard_hook.py"
        )
        checks.append(DoctorCheck(
            "action_guard_hook",
            hook_ok,
            hook_detail,
            "" if hook_ok else "恢复 hooks/action_guard_hook.py 后再加载 Claude Code 插件",
        ))

    install_root = Path(package_dir).parent if package_dir else Path.cwd()
    repository_demos = [install_root / "demo_route.py", install_root / "benchmark_route.py"]
    demo_detail = (
        "可运行: python demo_route.py / python benchmark_route.py（无需 API key）"
        if all(path.is_file() for path in repository_demos)
        else '可运行: task-router --route "写一个 Python 函数"（无需 API key）'
    )
    checks.append(DoctorCheck(
        "offline_demo",
        True,
        demo_detail,
    ))
    return checks


def format_doctor(checks: list[DoctorCheck]) -> tuple[str, int]:
    lines = ["task-api-router doctor", "=" * 48]
    failed = 0
    for item in checks:
        mark = "OK " if item.ok else "FAIL"
        if not item.ok:
            failed += 1
        lines.append(f"[{mark}] {item.name}: {item.detail}")
        if item.fix:
            lines.append(f"       → {item.fix}")
    ready_count = sum(1 for c in checks if c.ok)
    lines.append("-" * 48)
    if failed:
        lines.append(f"结果: {ready_count}/{len(checks)} 通过，{failed} 项需处理")
        lines.append("先修 FAIL 项，再执行: task-router --models")
    else:
        lines.append('结果: 全部通过。可试算: task-router --route "写一个 Python 函数"')
    return "\n".join(lines), failed
