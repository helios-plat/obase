"""obase.plugin_loader — 动态 Python / WASM 插件沙箱加载器.

职责:
- Python 插件: importlib 从任意路径加载，安装受限 meta_path 拦截器做沙箱
  （默认禁 os/subprocess/socket/importlib 等危险模块，白名单放行）。
- WASM 插件: 惰性依赖 wasmtime，导出函数封装为可调用 entry points。
- 统一返回 PluginSpec（name / version / entry_points / runtime）。

Example:
    >>> spec = load_python_plugin("my_plugin.py", name="greet")
    >>> spec.entry_points["main"]("world")
    'hello world'
"""

from __future__ import annotations

import builtins
import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "PluginSandboxError",
    "PluginSpec",
    "load_python_plugin",
    "load_plugin",
    "load_wasm_plugin",
    "DEFAULT_DENIED_MODULES",
]

DEFAULT_DENIED_MODULES = (
    "os",
    "subprocess",
    "socket",
    "shutil",
    "sys",
    "importlib",
    "ctypes",
    "pickle",
    "multiprocessing",
)


class PluginSandboxError(RuntimeError):
    """插件加载失败（语法错误 / 沙箱违规 / 依赖缺失）。"""


@dataclass
class PluginSpec:
    """加载完成的插件描述。"""

    name: str
    version: str
    runtime: str  # "python" | "wasm"
    source: Path
    entry_points: dict[str, Callable[..., Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, name: str) -> Callable[..., Any]:
        if name not in self.entry_points:
            raise KeyError(f"plugin {self.name!r} has no entry point {name!r}")
        return self.entry_points[name]

    def call(self, entry: str, *args: Any, **kwargs: Any) -> Any:
        """调用入口函数；不存在抛 PluginSandboxError。"""
        fn = self.entry_points.get(entry)
        if fn is None:
            raise PluginSandboxError(
                f"plugin {self.name!r} has no entry point {entry!r} "
                f"(available: {sorted(self.entry_points)})"
            )
        return fn(*args, **kwargs)


class _DenyFinder:
    """meta_path 拦截器：执行期间拒绝危险模块导入。"""

    def __init__(self, denied: tuple[str, ...]) -> None:
        self._denied = denied

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
        head = fullname.split(".")[0]
        if head in self._denied:
            raise PluginSandboxError(
                f"plugin sandbox: import of {fullname!r} is denied"
            )
        return None  # 放行其余模块（白名单语义之外维持正常解析）


def _parse_meta(path: Path, source: str) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for line in source.splitlines()[:20]:
        line = line.strip()
        if not line.startswith("# @"):
            continue
        key, _, value = line[3:].partition(":")
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta


def load_python_plugin(
    path: str | Path,
    *,
    name: str | None = None,
    allowed_modules: tuple[str, ...] = (),
    entry_points: tuple[str, ...] = ("main",),
) -> PluginSpec:
    """从 Python 文件加载插件（受限沙箱）。

    Args:
        path: 插件 .py 文件路径。
        name: 插件名；缺省取文件名 stem。
        allowed_modules: 白名单放行模块（覆盖默认拒绝列表中的同名模块）。
        entry_points: 需暴露的顶层函数名（调用期惰性取用）。

    Raises:
        PluginSandboxError: 文件缺失 / 语法错误 / 沙箱违规。
    """
    src = Path(path).resolve()
    if not src.exists():
        raise PluginSandboxError(f"plugin file not found: {src}")
    if src.suffix != ".py":
        raise PluginSandboxError(f"not a python file: {src}")
    try:
        source = src.read_text(encoding="utf-8")
    except OSError as exc:
        raise PluginSandboxError(f"cannot read plugin: {exc}") from exc

    meta = _parse_meta(src, source)
    plugin_name = name or meta.get("name") or src.stem
    denied = tuple(m for m in DEFAULT_DENIED_MODULES if m not in allowed_modules)

    finder = _DenyFinder(denied)
    sys.meta_path.insert(0, finder)
    real_import = builtins.__import__

    def _guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        head = name.split(".")[0]
        if head in denied:
            raise PluginSandboxError(
                f"plugin sandbox: import of {name!r} is denied"
            )
        return real_import(name, *args, **kwargs)

    builtins.__import__ = _guarded_import  # type: ignore[assignment]
    try:
        module_name = f"_obase_plugin_{plugin_name.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, src)
        if spec is None or spec.loader is None:
            raise PluginSandboxError(f"cannot create import spec for {src}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except PluginSandboxError:
            raise
        except Exception as exc:
            raise PluginSandboxError(
                f"plugin {plugin_name!r} failed to load: {type(exc).__name__}: {exc}"
            ) from exc
    finally:
        builtins.__import__ = real_import  # type: ignore[assignment]
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)

    entry: dict[str, Callable[..., Any]] = {}
    for ep in entry_points:
        fn = getattr(module, ep, None)
        if callable(fn):
            entry[ep] = fn
    return PluginSpec(
        name=plugin_name,
        version=meta.get("version", "0.0.0"),
        runtime="python",
        source=src,
        entry_points=entry,
        metadata=meta,
    )


def load_wasm_plugin(
    path: str | Path,
    *,
    name: str | None = None,
    entry_points: tuple[str, ...] = ("main",),
) -> PluginSpec:
    """从 WASM 文件加载插件（惰性依赖 wasmtime）。

    每个导出函数封装为 callable：调用时以 (instance, *args) 展开。
    导出函数的调用参数/返回均为 wasmtime 原生类型，调用方需自行 marshal。

    Raises:
        PluginSandboxError: wasmtime 未安装或加载失败。
    """
    src = Path(path).resolve()
    if not src.exists():
        raise PluginSandboxError(f"wasm file not found: {src}")
    try:
        import wasmtime  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - 环境相关
        raise PluginSandboxError(
            "wasmtime is not installed — run `pip install wasmtime`"
        ) from exc

    try:
        engine = wasmtime.Engine()
        module = wasmtime.Module.from_file(engine, str(src))
        store = wasmtime.Store(engine)
        instance = wasmtime.Instance(store, module, [])
    except Exception as exc:
        raise PluginSandboxError(f"wasm load failed: {exc}") from exc

    entry: dict[str, Callable[..., Any]] = {}
    for ep in entry_points:
        if not module.exports.get(ep):
            continue
        fn = instance.exports(store)[ep]

        def make(fn: Any = fn, ep: str = ep) -> Callable[..., Any]:
            def _call(*args: Any) -> Any:
                return fn(store, *args)

            _call.__name__ = ep
            return _call

        entry[ep] = make()

    return PluginSpec(
        name=name or src.stem,
        version="0.0.0",
        runtime="wasm",
        source=src,
        entry_points=entry,
    )


def load_plugin(path: str | Path, *, name: str | None = None) -> PluginSpec:
    """按文件后缀自动路由加载插件（.py → python，.wasm → wasm）。"""
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return load_python_plugin(path, name=name)
    if suffix == ".wasm":
        return load_wasm_plugin(path, name=name)
    raise PluginSandboxError(f"unsupported plugin runtime: {suffix!r}")
