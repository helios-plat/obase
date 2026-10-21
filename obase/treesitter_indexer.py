"""obase.treesitter_indexer — 代码符号索引（Tree-sitter，带 AST 回退）.

职责:
- 多语言符号提取（tree-sitter grammar；未安装时回退 Python ast 模块）
- 目录级索引：文件遍历 + 符号收集 + 语言统计
- tree-sitter / grammar 均为可选依赖：未安装时明确降级并标记 available=False

Example:
    >>> idx = TreesitterIndexer()
    >>> idx.available
    True   # 有 tree-sitter + grammar 时为 True；否则 ast 回退
    >>> syms = await idx.index_file("/repo/app.py")
    >>> syms[0]["name"]
    'main'
"""

from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

__all__ = [
    "CodeIndex",
    "SymbolRecord",
    "SymbolIndexer",
    "TreesitterIndexer",
    "AstFallbackIndexer",
    "LANGUAGE_EXTS",
]

LANGUAGE_EXTS: dict[str, tuple[str, ...]] = {
    "python": (".py", ".pyi"),
    "typescript": (".ts", ".tsx", ".mts", ".cts"),
    "javascript": (".js", ".jsx", ".mjs", ".cjs"),
    "go": (".go",),
    "rust": (".rs",),
    "java": (".java",),
    "c": (".c", ".h"),
    "cpp": (".cpp", ".cc", ".cxx", ".hpp"),
    "ruby": (".rb",),
    "csharp": (".cs",),
}

_IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", ".benchmarks",
}

SymbolKind = Literal["function", "class", "method", "import", "constant"]


@dataclass
class SymbolRecord:
    """单符号记录。"""

    name: str
    kind: SymbolKind
    path: str
    language: str
    line: int
    column: int = 0
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "path": self.path,
            "language": self.language,
            "line": self.line,
            "column": self.column,
            "signature": self.signature,
        }


@dataclass
class CodeIndex:
    """目录级索引结果。"""

    root: str
    files: list[str] = field(default_factory=list)
    symbols: list[SymbolRecord] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)

    @property
    def symbol_count(self) -> int:
        return len(self.symbols)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "files": list(self.files),
            "symbols": [s.to_dict() for s in self.symbols],
            "languages": dict(self.languages),
            "symbol_count": self.symbol_count,
        }


@runtime_checkable
class SymbolIndexer(Protocol):
    """符号索引器协议（oskill.repomap_gen 的注入面）。"""

    async def index_file(self, path: str | Path) -> list[SymbolRecord]: ...
    async def index_tree(self, root: str | Path, *, max_files: int = 500) -> CodeIndex: ...


# ---------------------------------------------------------------------------
# Tree-sitter 实现（可选依赖）
# ---------------------------------------------------------------------------


class TreesitterIndexer:
    """Tree-sitter 多语言符号索引器。

    - 未安装 tree_sitter → 自动回退 AstFallbackIndexer（仅 Python 精确，
      其余语言返回空），available=False。
    - 未安装对应语言 grammar → 该语言返回空符号集（不炸）。
    """

    _LANG_QUERIES: dict[str, tuple[str, ...]] = {
        "python": ("function_definition", "class_definition"),
        "typescript": ("function_declaration", "class_declaration", "method_definition"),
        "javascript": ("function_declaration", "class_declaration", "method_definition"),
        "go": ("function_declaration", "type_declaration"),
        "rust": ("function_item", "struct_item"),
        "java": ("method_declaration", "class_declaration"),
        "c": ("function_definition",),
        "cpp": ("function_definition", "class_specifier"),
        "ruby": ("method", "class"),
        "csharp": ("method_declaration", "class_declaration"),
    }

    def __init__(self) -> None:
        self._ts = None
        self._grammars: dict[str, Any] = {}
        self._available: bool | None = None

    @property
    def available(self) -> bool:
        """tree_sitter 主库是否可用（grammar 可部分缺失）。"""
        if self._available is None:
            try:
                import tree_sitter  # type: ignore[import-untyped]  # noqa: F401

                self._available = True
            except ImportError:
                self._available = False
        return self._available

    def _grammar(self, language: str) -> Any | None:
        if language in self._grammars:
            return self._grammars[language]
        mod_name = f"tree_sitter_{language}"
        try:
            mod = __import__(mod_name)
            grammar = mod.language
            self._grammars[language] = grammar
            return grammar
        except ImportError:
            self._grammars[language] = None
            return None

    async def index_file(self, path: str | Path) -> list[SymbolRecord]:
        src = Path(path)
        language = _language_of(src)
        if not language:
            return []
        if not self.available:
            return await AstFallbackIndexer().index_file(src)  # Python 精确回退
        grammar = self._grammar(language)
        if grammar is None:
            return []  # 语言 grammar 未装：空符号集（不炸）
        return await asyncio.to_thread(self._index_with_ts, src, language, grammar)

    def _index_with_ts(
        self, src: Path, language: str, grammar: Any
    ) -> list[SymbolRecord]:
        import tree_sitter  # type: ignore[import-untyped]

        parser = tree_sitter.Parser()
        parser.language = grammar()
        source = src.read_text(encoding="utf-8", errors="replace")
        tree = parser.parse(source.encode("utf-8"))
        records: list[SymbolRecord] = []
        _walk_ts(tree.root_node, source, src, language, records)
        return records

    async def index_tree(
        self, root: str | Path, *, max_files: int = 500
    ) -> CodeIndex:
        """递归索引目录（跳过 _IGNORE_DIRS 与 .git 文件）。"""
        root = Path(root)
        if not root.is_dir():
            raise FileNotFoundError(f"treesitter_indexer: root not found: {root}")

        files: list[Path] = []
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            if any(part in _IGNORE_DIRS for part in p.relative_to(root).parts):
                continue
            files.append(p)
            if len(files) >= max_files:
                break

        all_symbols: list[SymbolRecord] = []
        languages: dict[str, int] = {}
        for f in files:
            lang = _language_of(f)
            if lang:
                languages[lang] = languages.get(lang, 0) + 1
            all_symbols.extend(await self.index_file(f))

        return CodeIndex(
            root=str(root),
            files=[str(f) for f in files],
            symbols=all_symbols,
            languages=languages,
        )


def _walk_ts(
    node: Any,
    source: str,
    path: Path,
    language: str,
    records: list[SymbolRecord],
    depth: int = 0,
) -> None:
    if depth > 12:  # 防深递归
        return
    node_type = node.type
    if node_type in TreesitterIndexer._LANG_QUERIES.get(language, ()):
        name_node = _ts_name_node(node)
        if name_node is not None:
            start = node.start_point
            kind: SymbolKind = (
                "class"
                if "class" in node_type
                else "method"
                if "method" in node_type
                or node.parent
                and node.parent.type in ("class_body", "class_definition")
                else "function"
            )
            records.append(
                SymbolRecord(
                    name=source[name_node.start_byte : name_node.end_byte],
                    kind=kind,
                    path=str(path),
                    language=language,
                    line=start[0] + 1,
                    column=start[1],
                    signature=_ts_signature(source, node),
                )
            )
    for child in node.children:
        _walk_ts(child, source, path, language, records, depth + 1)


def _ts_name_node(node: Any) -> Any | None:
    for child in node.children:
        if child.type == "identifier" or child.type == "name" or child.type == "type_identifier":
            return child
    # 兜底：第一个 named child
    for child in node.children:
        if child.is_named:
            return child
    return None


def _ts_signature(source: str, node: Any) -> str:
    return source[node.start_byte : node.end_byte].splitlines()[0][:120]


# ---------------------------------------------------------------------------
# AST 回退实现（Python 精确，无外部依赖）
# ---------------------------------------------------------------------------


class AstFallbackIndexer:
    """零依赖 ast 回退：Python 文件符号提取；其他语言返回空。"""

    async def index_file(self, path: str | Path) -> list[SymbolRecord]:
        src = Path(path)
        if _language_of(src) != "python":
            return []
        try:
            tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))
        except (SyntaxError, OSError):
            return []
        records: list[SymbolRecord] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                async_prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
                arg_names = ", ".join(a.arg for a in node.args.args)
                records.append(
                    SymbolRecord(
                        name=node.name,
                        kind="function",
                        path=str(src),
                        language="python",
                        line=node.lineno,
                        signature=f"{async_prefix}def {node.name}({arg_names})",
                    )
                )
            elif isinstance(node, ast.ClassDef):
                records.append(
                    SymbolRecord(
                        name=node.name,
                        kind="class",
                        path=str(src),
                        language="python",
                        line=node.lineno,
                    )
                )
                for m in node.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        records.append(
                            SymbolRecord(
                                name=m.name,
                                kind="method",
                                path=str(src),
                                language="python",
                                line=m.lineno,
                            )
                        )
            elif isinstance(node, ast.Import):
                for a in node.names:
                    records.append(
                        SymbolRecord(
                            name=a.name.split(".")[0],
                            kind="import",
                            path=str(src),
                            language="python",
                            line=node.lineno,
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    records.append(
                        SymbolRecord(
                            name=a.name,
                            kind="import",
                            path=str(src),
                            language="python",
                            line=node.lineno,
                        )
                    )
        return records

    async def index_tree(
        self, root: str | Path, *, max_files: int = 500
    ) -> CodeIndex:
        """AST 回退版目录索引：仅精确索引 Python 文件。"""
        root = Path(root)
        if not root.is_dir():
            raise FileNotFoundError(f"treesitter_indexer: root not found: {root}")

        files: list[Path] = []
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            if any(part in _IGNORE_DIRS for part in p.relative_to(root).parts):
                continue
            files.append(p)
            if len(files) >= max_files:
                break

        all_symbols: list[SymbolRecord] = []
        languages: dict[str, int] = {}
        for f in files:
            lang = _language_of(f)
            if lang:
                languages[lang] = languages.get(lang, 0) + 1
            if lang == "python":
                all_symbols.extend(await self.index_file(f))

        return CodeIndex(
            root=str(root),
            files=[str(f) for f in files],
            symbols=all_symbols,
            languages=languages,
        )


def _language_of(path: Path) -> str | None:
    ext = path.suffix.lower()
    for lang, exts in LANGUAGE_EXTS.items():
        if ext in exts:
            return lang
    return None
