# BUG-005：pytest 默认临时目录不可访问

## 复现与影响

使用 `tmp_path` 的 4 个测试在 setup 阶段报 `PermissionError`，不使用临时目录的 4 个测试通过。错误路径为用户级 `AppData/Local/Temp/pytest-of-Administrator`。

## 根因

pytest 默认 basetemp 位于当前受控环境不可访问的用户临时目录。

## 修复

在 `pyproject.toml` 中统一配置 `--basetemp=.pytest-tmp`，并将目录加入 `.gitignore`。测试临时文件由此限定在项目工作区。

## 验证

全量重跑领域模型和 Tool 注册表测试，不再出现 fixture 初始化权限错误。

