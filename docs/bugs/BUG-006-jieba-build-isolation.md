# BUG-006：jieba 构建隔离阻塞环境安装

## 复现与影响

核心依赖安装在下载 `jieba-0.42.1.tar.gz` 后长期停留于 `Installing build dependencies`。其他核心依赖均有 Windows wheel，只有 jieba 触发独立构建环境。

## 根因

jieba 在当前包源仅提供源码分发；pip 构建隔离需要再次访问网络下载构建依赖，而当前网络对元数据请求不稳定。

## 修复

- jieba 从强制运行依赖改为可选加速后端。
- RAG tokenizer 在 jieba 不可用时使用中文单字、双字和英文词元的确定性降级。
- BM25、字符 n-gram 向量和 RRF 主链路保持不变。

## 验证

- 无 jieba 环境可以导入并运行 RAG。
- 口径定义和版本变更两条检索测试仍需通过。

