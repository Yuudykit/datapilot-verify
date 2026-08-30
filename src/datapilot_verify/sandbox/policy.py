from __future__ import annotations

import ast


class PythonPolicy:
    ALLOWED_IMPORTS = {"math", "statistics", "pandas", "numpy", "polars", "scipy"}
    BLOCKED_CALLS = {
        "breakpoint",
        "compile",
        "delattr",
        "eval",
        "exec",
        "getattr",
        "globals",
        "help",
        "input",
        "locals",
        "open",
        "setattr",
        "vars",
        "__import__",
    }
    BLOCKED_ATTRIBUTES = {
        "chmod",
        "connect",
        "environ",
        "eval",
        "exec",
        "fork",
        "kill",
        "mkdir",
        "popen",
        "remove",
        "rename",
        "replace",
        "rmdir",
        "socket",
        "spawn",
        "symlink",
        "system",
        "to_csv",
        "to_excel",
        "to_hdf",
        "to_json",
        "to_parquet",
        "to_pickle",
        "to_sql",
        "unlink",
        "write_bytes",
        "write_text",
    }
    # 数据读取统一约束到注入的 input_csv，避免 read_json/read_pickle 等
    # 非白名单 reader 读取任意路径甚至 URL（read_json 支持网络地址）。
    DATA_READER_PREFIXES = ("read_", "scan_")

    def validate(self, code: str) -> ast.Module:
        try:
            tree = ast.parse(code, mode="exec")
        except SyntaxError as exc:
            raise ValueError(f"invalid Python syntax: {exc.msg}") from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._validate_import(alias.name)
            elif isinstance(node, ast.ImportFrom):
                self._validate_import(node.module or "")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in self.BLOCKED_CALLS:
                    raise ValueError(f"blocked Python call: {node.func.id}")
            elif isinstance(node, ast.Attribute):
                if node.attr.casefold() in self.BLOCKED_ATTRIBUTES or node.attr.startswith("__"):
                    raise ValueError(f"blocked Python attribute: {node.attr}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr.startswith(self.DATA_READER_PREFIXES):
                    if not node.args or not isinstance(node.args[0], ast.Name):
                        raise ValueError("data readers must use the injected input_csv variable")
                    if node.args[0].id != "input_csv":
                        raise ValueError("data readers must use the injected input_csv variable")
            elif isinstance(node, ast.Name) and node.id.startswith("__"):
                raise ValueError(f"blocked Python name: {node.id}")
        return tree

    def _validate_import(self, module: str) -> None:
        root = module.split(".", 1)[0]
        if root not in self.ALLOWED_IMPORTS:
            raise ValueError(f"blocked Python import: {module}")
