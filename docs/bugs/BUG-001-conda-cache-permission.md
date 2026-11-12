# BUG-001：Conda 默认缓存目录不可写

## 摘要

首次执行 `conda create --prefix D:\datapilot-verify\.conda-env python=3.11 pip -y` 失败，Conda 默认配置的包缓存目录均不具备写权限。

## 影响

- 无法创建项目要求的 Conda Python 3.11 环境。
- 与业务代码无关，但阻塞全部后续开发和测试。

## 复现

```powershell
conda create --prefix D:\datapilot-verify\.conda-env python=3.11 pip -y
```

错误：`NoWritablePkgsDirError`，默认目录包括 `D:\Anaconda\pkgs` 和用户 `.conda\pkgs`。

## 根因

当前受控工作区只允许向项目目录写入；Conda 即使使用 `--prefix` 创建本地环境，默认仍把下载包写入全局/用户缓存。

## 修复

在创建环境的进程中设置：

```powershell
$env:CONDA_PKGS_DIRS='D:\datapilot-verify\.conda-pkgs'
$env:CONDA_ENVS_PATH='D:\datapilot-verify\.conda-envs'
```

然后继续使用项目内前缀 `D:\datapilot-verify\.conda-env`。

## 验证

- Python 3.11.16 环境创建成功。
- 环境可通过完整路径激活和执行。
- Conda 无法写入用户级 `environments.txt` 仅产生注册警告，不影响环境本身。

## 预防

- README 明确项目环境与缓存路径。
- CI 和本地脚本不依赖环境已注册到 Conda 用户列表。

