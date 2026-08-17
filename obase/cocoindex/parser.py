"""obase.cocoindex.parser — file/source → AST node list. No Veya logic."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


class ASTParser:
    """Tree-sitter when present; stdlib ast otherwise. Result names the backend."""

    def parse_source(self, source: str, *, language: str = "python") -> dict[str, Any]:
        if language != "python":
            return {
                "ok": False,
                "backend": "",
                "nodes": [],
                "error": f"unsupported language {language!r}",
            }
        try:
            return self._parse_tree_sitter(source)
        except Exception:
            return self._parse_stdlib(source)

    async def parse_file(self, filepath: Path) -> dict[str, Any]:
        path = Path(filepath)
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "backend": "", "nodes": [], "error": str(exc)}
        rec = self.parse_source(source, language="python")
        rec["path"] = str(path)
        return rec

    def _parse_tree_sitter(self, source: str) -> dict[str, Any]:
        import tree_sitter_python as tsp
        from tree_sitter import Language, Parser

        parser = Parser(Language(tsp.language()))
        tree = parser.parse(source.encode("utf-8"))
        nodes = _from_tree_sitter(tree.root_node, source.encode("utf-8"))
        return {"ok": True, "backend": "tree_sitter", "nodes": nodes, "error": ""}

    def _parse_stdlib(self, source: str) -> dict[str, Any]:
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return {"ok": False, "backend": "stdlib_ast", "nodes": [], "error": str(exc)}
        return {"ok": True, "backend": "stdlib_ast", "nodes": _from_stdlib(tree), "error": ""}


def _from_stdlib(tree: ast.AST) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nodes.append(
                {
                    "kind": "function",
                    "name": item.name,
                    "arity": len(item.args.args),
                    "shape": _stdlib_shape(item),
                    "constants": _stdlib_constants(item),
                    "line": int(getattr(item, "lineno", 0) or 0),
                }
            )
        elif isinstance(item, ast.ClassDef):
            nodes.append(
                {
                    "kind": "class",
                    "name": item.name,
                    "arity": 0,
                    "shape": ",".join(
                        n.name
                        for n in item.body
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ),
                    "constants": _stdlib_constants(item),
                    "line": int(getattr(item, "lineno", 0) or 0),
                }
            )
        elif isinstance(item, ast.Assign):
            names = [
                t.id for t in item.targets if isinstance(t, ast.Name)
            ]
            value = _literal(item.value)
            if names and value is not None:
                nodes.append(
                    {
                        "kind": "constant",
                        "name": names[0],
                        "arity": 0,
                        "shape": "",
                        "constants": [value],
                        "line": int(getattr(item, "lineno", 0) or 0),
                    }
                )
    return nodes


def _stdlib_shape(fn: ast.AST) -> str:
    kinds: list[str] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.If):
            kinds.append("if")
        elif isinstance(node, ast.For):
            kinds.append("for")
        elif isinstance(node, ast.While):
            kinds.append("while")
        elif isinstance(node, ast.Return):
            kinds.append("return")
        elif isinstance(node, ast.Raise):
            kinds.append("raise")
    return ",".join(kinds)


def _stdlib_constants(root: ast.AST) -> list[str]:
    values: list[str] = []
    for node in ast.walk(root):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool)):
            values.append(repr(node.value))
    return values


def _literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool)):
        return repr(node.value)
    return None


def _from_tree_sitter(root: Any, source: bytes) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for child in root.children:
        kind = child.type
        if kind in {"function_definition", "async_function_definition"}:
            name = _ts_name(child, source)
            nodes.append(
                {
                    "kind": "function",
                    "name": name,
                    "arity": _ts_arity(child),
                    "shape": _ts_shape(child),
                    "constants": _ts_constants(child, source),
                    "line": child.start_point[0] + 1,
                }
            )
        elif kind == "class_definition":
            name = _ts_name(child, source)
            methods = [
                _ts_name(n, source)
                for n in _ts_walk(child)
                if n.type in {"function_definition", "async_function_definition"}
            ]
            nodes.append(
                {
                    "kind": "class",
                    "name": name,
                    "arity": 0,
                    "shape": ",".join(m for m in methods if m),
                    "constants": _ts_constants(child, source),
                    "line": child.start_point[0] + 1,
                }
            )
        elif kind == "expression_statement":
            assign = _ts_assignment(child, source)
            if assign:
                nodes.append(assign)
    return nodes


def _ts_walk(node: Any):
    yield node
    for child in node.children:
        yield from _ts_walk(child)


def _ts_text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _ts_name(node: Any, source: bytes) -> str:
    for child in node.children:
        if child.type == "identifier":
            return _ts_text(child, source)
    return ""


def _ts_arity(node: Any) -> int:
    for child in node.children:
        if child.type == "parameters":
            return sum(1 for c in child.children if c.type == "identifier")
    return 0


def _ts_shape(node: Any) -> str:
    kinds: list[str] = []
    for child in _ts_walk(node):
        if child.type == "if_statement":
            kinds.append("if")
        elif child.type == "for_statement":
            kinds.append("for")
        elif child.type == "while_statement":
            kinds.append("while")
        elif child.type == "return_statement":
            kinds.append("return")
        elif child.type == "raise_statement":
            kinds.append("raise")
    return ",".join(kinds)


def _ts_constants(node: Any, source: bytes) -> list[str]:
    values: list[str] = []
    for child in _ts_walk(node):
        if child.type in {"string", "integer", "float", "true", "false"}:
            values.append(_ts_text(child, source))
    return values


def _ts_assignment(node: Any, source: bytes) -> dict[str, Any] | None:
    for child in node.children:
        if child.type != "assignment":
            continue
        left = ""
        right = ""
        kids = [c for c in child.children if c.type not in {"=", ","}]
        if len(kids) >= 2 and kids[0].type == "identifier":
            left = _ts_text(kids[0], source)
            right = _ts_text(kids[1], source)
        if left:
            return {
                "kind": "constant",
                "name": left,
                "arity": 0,
                "shape": "",
                "constants": [right],
                "line": child.start_point[0] + 1,
            }
    return None


