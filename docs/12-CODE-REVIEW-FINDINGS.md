# Code Review Findings — Post-Sprint Audit

Reviewed after completing the E1–E3 / C1–C3 sprint (all GitHub issues closed).
Audited by: superpowers:code-reviewer agent, 2026-04-28.

**All Critical and Important findings below are FIXED in commit `ed46d55` (2026-04-28).**
GitHub issues #30–#38 track each CodeRabbit finding; all are closed.

---

## Critical — All Fixed ✅

### C1 — `StopIteration` in async backtest runner ✅ FIXED
**File:** [src/backtest/runner.py](../src/backtest/runner.py)

Replaced `raise StopIteration` with custom `_BacktestDone` exception. `except _BacktestDone: pass` in the backtest runner restores `asyncio.sleep` correctly in all code paths.

---

### C2 — Fill-confirmation sleep advances backtest candle cursor ✅ FIXED
**Files:** [src/backtest/simulated_api.py](../src/backtest/simulated_api.py), [src/loop/executor.py](../src/loop/executor.py)

`SimulatedAPI` now has `is_simulation = True`. `executor.py` skips the fill-confirmation `asyncio.sleep(1)` when `getattr(hyperliquid, 'is_simulation', False)` is true.

---

### C3 — Kelly criterion silently ignores all short trades ✅ FIXED
**File:** [src/intelligence/kelly.py](../src/intelligence/kelly.py)

`executor.py` writes `is_long` boolean to every diary entry. `_parse_trade_returns` in `kelly.py` uses `is_long` to distinguish open vs close for both longs and shorts. All short round-trips are now correctly paired and included in the Kelly calculation.

---

## Important — All Fixed ✅

### I1 — Force-close removal not immediately persisted to DB ✅ FIXED
**File:** [src/loop/runner.py](../src/loop/runner.py)

`save_all_active_trades` is called immediately after each successful force-close removal, before the cycle continues.

---

### I2 — Mixed naive/UTC-aware datetimes ✅ FIXED
**File:** [src/loop/executor.py](../src/loop/executor.py)

All `datetime.now()` calls replaced with `datetime.now(timezone.utc).isoformat()`. Diary entries and `active_trades` DB records are now consistently UTC-aware.

---

### I3 — Sequential price fetches per position ✅ FIXED
**Files:** [src/loop/state_builder.py](../src/loop/state_builder.py), [src/loop/runner.py](../src/loop/runner.py)

`state_builder.py` uses `asyncio.gather` for concurrent per-position price fetches with `return_exceptions=True`. `runner.py` wraps `build_account_state` in `try/except` with fallback to raw state values.

---

### I4 — Kelly replaces LLM allocation instead of capping it ✅ FIXED
**File:** [src/loop/executor.py](../src/loop/executor.py)

Kelly now caps rather than replaces: `alloc_usd = kelly_usd` only when `alloc_usd > kelly_usd`. LLM per-asset conviction signals are preserved for smaller allocations.

---

### I5 — `db_path` derivation corrupts directory name ✅ FIXED
**File:** [src/loop/runner.py](../src/loop/runner.py)

Replaced `str.replace` with `pathlib.Path.with_name()` so the rename applies only to the filename component, not the directory path.

---

## Suggestions — Nice to Have

| ID | File | Issue |
|----|------|-------|
| S1 | [src/loop/runner.py:22-31](../src/loop/runner.py#L22) | Live Sharpe reads non-existent `pnl` field from `trade_log`; always displays 0.0 |
| S2 | [src/backtest/simulated_api.py:136-143](../src/backtest/simulated_api.py#L136) | Naked short sell (no position) adds phantom balance instead of rejecting |
| S3 | [src/loop/runner.py:313](../src/loop/runner.py#L313) | `decisions.jsonl` hardcoded to cwd, not relative to `diary_path` |
| S4 | [src/backtest/runner.py:91](../src/backtest/runner.py#L91) | `total_trades` counts fills (buy+sell separately), not round-trips — inconsistent with `win_rate_pct` |
| S5 | [src/loop/learning.py](../src/loop/learning.py), [src/intelligence/kelly.py](../src/intelligence/kelly.py) | Diary read once per asset per cycle; should consolidate to one read |

---

## Test Coverage Gaps

The following scenarios have no test coverage:
1. `run_backtest` with a minimal candle dataset (would immediately catch C1)
2. Kelly with short-trade diary entries (would catch C3)
3. `build_account_state` exception propagation through `runner.py`
4. `db_path` derivation with "diary" in the directory component (would catch I5)
5. `SimulatedAPI._fill_order` naked-short path (would catch S2)
