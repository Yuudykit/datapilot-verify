# BUG-004：Windows CLI 中文输出乱码

## 复现与影响

执行造数脚本后，JSON 中的华东、华北等区域在终端显示为替换字符，文件内容本身正常。该问题会破坏 CLI 演示和日志可读性。

## 根因

当前 Python stdout 编码与宿主 PowerShell/Codex 输出解码不一致。

## 修复

CLI 入口和独立造数脚本启动时显式将 `sys.stdout` 配置为 UTF-8；数据文件继续显式使用 UTF-8/UTF-8 BOM。

## 验证

重新运行造数脚本，终端区域名称和 JSON 文件均应正确显示中文。

