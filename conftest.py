"""Pytest 会话兜底（BUG-013）。

Windows 沙箱进程可能把项目内的 pytest 目录留在连 Administrator 都无法
读取 ACL 的状态（takeown/icacls/rmdir 均拒绝访问）。pytest 的
TempPathFactory 在首个用例前会 rmtree(basetemp)，删除失败会让整个会话
在 setup 阶段直接报错。这里在会话配置阶段提前探测：basetemp 清不掉就
整体重定向到后备目录，并同步修正已创建工厂的既定路径。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

_FALLBACK_SUFFIXES = ("-fallback", "-fallback2")


def _clearable(directory: Path) -> bool:
    if not directory.exists():
        return directory.parent.is_dir() and os.access(directory.parent, os.W_OK)
    try:
        shutil.rmtree(directory)
    except OSError:
        return False
    return True


def pytest_configure(config: pytest.Config) -> None:
    basetemp = config.getoption("basetemp") or ".pytest-tmp"
    root = Path(basetemp)
    if not root.is_absolute():
        root = config.rootpath / root
    if _clearable(root):
        return
    for suffix in _FALLBACK_SUFFIXES:
        fallback = root.with_name(root.name + suffix)
        if _clearable(fallback):
            config.option.basetemp = str(fallback)
            factory = getattr(config, "_tmp_path_factory", None)
            if factory is not None:
                factory._given_basetemp = Path(os.path.abspath(str(fallback)))
            return
    raise RuntimeError(f"pytest basetemp 不可用且后备目录创建失败：{root}")
