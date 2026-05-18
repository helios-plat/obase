# obase v0.1.0 Cleanup Audit Report

**审计日期**: 2026-05-18  
**审计者**: CC (OBASE_CLEANUP_TASKS v0.1 PR 1)  
**基准 commit**: `8cf415a fix(B-1): merge Stratum-native cost tracking into obase.cost_tracker main trunk`

---

## 0. 实际状态 vs 任务包描述的偏差

任务包 §0 描述 5 个污染文件，实际扫描结果：

| 文件 | 任务包描述 | 实际状态 |
|---|---|---|
| `errors.py` | 存在，需删除 | **EXISTS** (59 行) |
| `logging.py` | 存在，需删除 | **EXISTS** (44 行) |
| `config.py` | 存在，需删除 | **EXISTS** (31 行) |
| `bootstrap_stratum.py` | 存在，需删除 | **MISSING**（已不在仓库） |
| `cost_tracker_stratum.py` | 存在，需删除 | **MISSING**（内容已被 commit `8cf415a` 合并进 `cost_tracker.py` 主干） |

**实际需要处理的污染只有 3 个文件**。但 `cost_tracker.py` 因合并引入了新的争议点（见 §5）。

---

## 1. 3 个污染文件内容摘要

### 1.1 errors.py（59 行）

**主要内容**：13 个 Stratum 特定异常类，全部继承 `StratumError`（本身继承 `Exception`）

```
StratumError (base)
├── ConfigError
├── PDFParseError
├── UnsupportedFileTypeError
├── UnsupportedImageError
├── EmbeddingError
├── QuotaExceededError
├── VectorDBError
├── FulltextError
├── MetaDBError
├── LLMError
│   └── LLMRateLimitError
├── IngestError
└── DuplicateSubstrateError
```

**与 obase.exceptions 的重叠**：
- 无重名类
- 但 `QuotaExceededError` 与 `obase.exceptions.RateLimitExceeded` 语义重叠
- `ConfigError` 与 `obase.exceptions.OBaseError`（通过 `hevi.errors.ConfigError`）间接重叠
- **这些类全部是 Stratum 业务相关**（PDF / 向量库 / 嵌入 / 全文索引），不是横切基础设施

**外部依赖**：无（stdlib only）

---

### 1.2 logging.py（44 行）

**主要内容**：Stratum 特定 logging 模块，基于 stdlib `logging`（**不是** obase Helios 层用的 structlog）

函数：`setup_logging(level)` / `emit(event_type, **kwargs)` / `error(msg, **kwargs)` / `warning(msg, **kwargs)` / `info(msg, **kwargs)` / `_payload(event_type, **kwargs)`（私有）

**与 obase Helios 层的重叠/差异**：
- obase Helios 层（orchestrator / trail / cost_tracker）使用 `structlog.get_logger()`
- `logging.py` 使用 stdlib `logging.getLogger("stratum")`
- 两套独立，不共用，仅命名空间相同（都在 `obase` 包下）
- **假设了 Stratum 业务**：logger name 硬编码 `"stratum"`，无法配置

**是否有 obase.bootstrap 没有的能力**：否。`obase.bootstrap` 用 structlog 初始化，功能更完整。

**外部依赖**：无（stdlib only）

---

### 1.3 config.py（31 行）

**主要内容**：Stratum 特定 config 加载，读 `~/.stratum/config.yaml`，加载 `DASHSCOPE_API_KEY` / `ANTHROPIC_API_KEY` 和所有 `STRATUM_*` 前缀环境变量。

函数：`load_config(path)` / `get(key, default=None)`

**与 obase.bootstrap.load_env 的重叠/差异**：
- `obase.bootstrap.load_env` 加载 `.env` 文件，处理行内注释 / 空值 / URL 校验
- `config.py` 加载 YAML + 环境变量
- 两者目的类似（初始化时获取配置），但格式和用途不同
- **假设了 Stratum 业务**：硬编码 `~/.stratum/` 路径、`STRATUM_` 前缀、`DASHSCOPE_API_KEY`

**是否有 obase.bootstrap 没有的能力**：
- YAML 配置文件加载（obase.bootstrap 只支持 .env 格式）
- 但 YAML 配置这个需求属于 Stratum 自己的功能，不是横切基础设施

**外部依赖**：`pyyaml`（已在 obase 依赖中）

---

## 2. 内部引用检查

### 2.1 obase 包内 import 这 3 个文件的位置

| 文件 | 引用位置 | 引用内容 |
|---|---|---|
| `errors.py` | `obase/__init__.py` 第 14-29 行 | eagerly import 全部 13 个异常类到顶层 namespace |
| `logging.py` | `cost_tracker.py` 第 34-43 行 | `from obase import logging as _olog`（**wrapped in try/except**，失败静默） |
| `config.py` | 无 obase 内部引用 | |

**`obase/__init__.py` 对 `errors.py` 的 eager import 是最大的依赖**：

```python
# obase/__init__.py 第 11-29 行
from obase.errors import (
    ConfigError, DuplicateSubstrateError, EmbeddingError, ...  # 13 个
)
```

删除 `errors.py` 前，必须先清理 `__init__.py` 的这 16 行。

**`cost_tracker.py` 对 `logging.py` 的引用**：

```python
# cost_tracker.py 第 34-43 行（在 track() 函数内）
try:
    from obase import logging as _olog
    _olog.info("obase.cost_tracker.track", ...)
except Exception:
    pass  # ← 静默，不会 ImportError
```

删除 `logging.py` 后，这段代码 try/except 会静默通过，**不会破坏任何功能**。但这行代码本身也属于 Stratum-native 污染（调用了 Stratum logging）。

### 2.2 tests/ 中针对这 3 个文件的测试

**`tests/test_obase.py`（177 行）** 覆盖了全部 3 个污染文件 + cost_tracker 模块级函数：

| 测试类 | 对应污染 | 测试数 |
|---|---|---|
| `TestErrors` | `errors.py` | 5 |
| `TestLogging` | `logging.py` | 6 |
| `TestConfig` | `config.py` | 6 |
| `TestCostTracker` | `cost_tracker.py` 模块级函数（见 §5） | 6 |

**删除 3 个污染文件后，`TestErrors` / `TestLogging` / `TestConfig` 这 17 个测试必须同步删除**。

`TestCostTracker` 的 6 个测试是针对 `cost_tracker.py` 里**合并进来的 Stratum-native 模块级函数**（`track` / `total_cost` / `reset`），这 6 个测试的命运取决于 advisor 对 §5 问题的决策。

### 2.3 examples/ 引用情况

无（`grep` 无输出）。

### 2.4 docs/ 引用情况

无（`grep` 无输出）。

---

## 3. 外部影响检查

### 3.1 hevi 仓库 import 这 3 个文件

`grep -rn "from obase.errors|from obase.logging|from obase.config" hevi/ scripts/ tests/` → **(no results)**

**结论**：hevi 不依赖任何污染文件，删除不影响 hevi。

---

## 4. 删除安全性结论

| 文件 | 删除安全？ | 前提条件 |
|---|---|---|
| `errors.py` | ☑ 安全（无外部依赖） | 必须先清理 `obase/__init__.py`（删除 eager import 的 16 行）和 `tests/test_obase.py::TestErrors`（5 个测试） |
| `logging.py` | ☑ 安全（无外部依赖） | `cost_tracker.py` 内的 `try: from obase import logging` 在删除后静默通过，无需修改。需删除 `tests/test_obase.py::TestLogging`（6 个测试） |
| `config.py` | ☑ 安全（无外部依赖） | 需删除 `tests/test_obase.py::TestConfig`（6 个测试） |

**合计**: 3 个文件全部可以安全删除，需同步：
- 清理 `obase/__init__.py`（14 行 import + `__all__` 中的 14 条目）
- 删除或清理 `tests/test_obase.py`（删除 `TestErrors` / `TestLogging` / `TestConfig` 共 17 个测试）

---

## 5. ⚠️ B-1 合并引入的争议点（需 advisor 决策）

commit `8cf415a` 将 `cost_tracker_stratum.py` 的内容合并进了 `cost_tracker.py` 主干，在文件前部（第 10-59 行）加入了：

```python
# 模块级轻量成本追踪（stdlib only）
@dataclass
class CostRecord:  # 注意：与 hevi._types.CostRecord 同名但不同
    provider: str; model: str; input_tokens: int; output_tokens: int; cost_usd: float

_records: list[CostRecord] = []
_lock = Lock()

def track(provider, model, input_tokens, output_tokens, cost_usd): ...
def total_cost() -> float: ...
def get_records() -> list[CostRecord]: ...
def reset() -> None: ...
```

这 4 个函数是**不同于 `CostTracker` class 的独立 API**，API 风格完全不同：
- 全局状态（module-level `_records`），无 run_id，无 pricing_table
- 参数是 `input_tokens` / `output_tokens`（原始 tokens）而非 category/unit 抽象
- 无预算保护，无 trail 集成

**这些函数是否违反 OBASE_SPEC §1.1？**

分析：
- 它们本身不假设"某个业务"，属于轻量计量工具
- 但 `track()` 内部 `from obase import logging as _olog` 调用了 Stratum logging（虽然 try/except 静默）
- 它们被 `tests/test_obase.py::TestCostTracker` 测试，测试用例用的是 Stratum 特定的 provider 名称（`"dashscope"`）

**advisor 需要二选一**：

**选项 A（保留）**：认为 `track/total_cost/reset` 是合法的横切轻量 API，保留在 `cost_tracker.py`。同时：
  - 清理 `track()` 内的 `from obase import logging` 调用（改用 structlog 或删除 logging）
  - 保留 `tests/test_obase.py::TestCostTracker` 的 6 个测试（或移到 `test_cost_tracker.py`）
  - `TestCostTracker` 测试内的 `"dashscope"` provider 名改为通用名（如 `"vendor_a"`）

**选项 B（移除）**：认为模块级全局函数不符合 obase 有状态基础设施的 DI 设计原则（OBASE_SPEC §1.4），删除 `track/total_cost/get_records/reset` 和 `CostRecord` dataclass。同时删除 `tests/test_obase.py::TestCostTracker` 的 6 个测试。

---

## 6. CC 的疑问

1. **obase 定位是否已发生变化**？obase `__init__.py` 的注释写 `"Stratum core utilities + legacy infrastructure library"`，而 OBASE_SPEC §0.1 写的是"Helios 生态横切基础设施"。两者似乎在发生冲突。本次清理是否同时澄清 obase 的官方定位？

2. **`logging.py` 中的 logger name `"stratum"`**：即使决定保留 `logging.py`，这个 hardcoded name 是否应该改为可配置（比如 `setup_logging(name="obase")`）？还是直接删除更干净？

3. **删除后 obase 测试数量的变化**：
   - 当前：157 tests
   - 删 3 个文件 + TestErrors/TestLogging/TestConfig（17 tests）后：≈ 140 tests
   - 若同时删 TestCostTracker（选项 B）：≈ 134 tests（回到 8cf415a 之前的数字）

---

## 7. 给 advisor 的建议

**建议直接删除 3 个污染文件**（errors.py / logging.py / config.py），同步处理：
1. 清理 `obase/__init__.py`：删除 Stratum-native import 块，恢复为纯 Helios 导出
2. 删除 `tests/test_obase.py::TestErrors` / `TestLogging` / `TestConfig`（17 个测试）

**对 §5 B-1 合并问题**，建议 **选项 B（移除模块级函数）**：
- `track/total_cost/reset` 违反 OBASE_SPEC §1.4 DI 原则（全局状态）
- `obase.cost_tracker` 的正式 API 是 `CostTracker` class，不应有平行全局 API
- 移除后 `cost_tracker.py` 只保留 Helios `PricingEntry` / `PricingTable` / `CostTracker`，语义清晰

**若 advisor 选择选项 A**，需额外在 `cost_tracker.py` 里把 `from obase import logging` 改掉，否则形成对污染 `logging.py` 的内部依赖闭环。

---

## 8. 操作总结（等 advisor 确认后 PR 2 执行）

**一定要删除**：
- `obase/errors.py`
- `obase/logging.py`
- `obase/config.py`
- `obase/__init__.py`：删除第 11-47 行 Stratum-native 块（含 eager import + `__all__` 条目）
- `tests/test_obase.py::TestErrors`（5 tests）
- `tests/test_obase.py::TestLogging`（6 tests）
- `tests/test_obase.py::TestConfig`（6 tests）

**等 advisor 决策**：
- `cost_tracker.py` 前 50 行的模块级函数（选项 A 保留 / 选项 B 删除）
- `tests/test_obase.py::TestCostTracker`（6 tests，与上面联动）

**完成后预期测试数**：
- 选项 A（保留模块级函数）：≈ 140 tests
- 选项 B（删除模块级函数）：≈ 134 tests
