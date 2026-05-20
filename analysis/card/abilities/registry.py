"""abilities/registry.py — 主注册表。

集中注册所有 Spell / TargetSelector / Condition / ValueProvider。
在初始化时自动发现并导入各模块。
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Dict

log = logging.getLogger(__name__)

# 已初始化标记
_INITIALIZED = False


def init_all():
    """初始化所有注册表。

    自动导入所有 Spell 子模块（触发 @register_spell 装饰器）。
    需要在应用启动时调用一次。
    """
    global _INITIALIZED
    if _INITIALIZED:
        return

    # 自动发现并导入 spells/ 下的所有模块
    _auto_import_package("analysis.card.spells")

    # 确保条件/值系统已加载
    import analysis.card.condition.conditions  # noqa: F401
    import analysis.card.value.providers  # noqa: F401

    _INITIALIZED = True
    log.info("v2 Spell 系统初始化完成")


def _auto_import_package(package_name: str):
    """自动导入包下的所有子模块。"""
    try:
        package = importlib.import_module(package_name)
    except ImportError:
        log.warning("无法导入包 %s", package_name)
        return

    if hasattr(package, '__path__'):
        for importer, modname, ispkg in pkgutil.iter_modules(package.__path__):
            full_name = f"{package_name}.{modname}"
            try:
                importlib.import_module(full_name)
            except ImportError as e:
                log.warning("自动导入 %s 失败: %s", full_name, e)


def spell_classes() -> Dict[str, type]:
    """返回所有已注册的 Spell 类名 → 类 映射。"""
    from analysis.card.spells import SPELL_REGISTRY
    return dict(SPELL_REGISTRY)


def available_spells() -> list:
    """返回已注册的 Spell 类名列表。"""
    return sorted(spell_classes().keys())
