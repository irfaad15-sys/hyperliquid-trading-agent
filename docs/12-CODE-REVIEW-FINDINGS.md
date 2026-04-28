# Code Review Findings — Post-Sprint Audit

Reviewed after completing the E1–E3 / C1–C3 sprint (all GitHub issues closed).
Audited by: superpowers:code-reviewer agent, 2026-04-28.

---

## Critical — Fix Before Testnet

### C1 — `StopIteration` in async backtest runner
**File:** [src/backtest/runner.py:124](../src/backtest/runner.py#L124)

PEP 479 (enforced Python 3.7+) converts any `StopIteration` raised inside a coroutine into `RuntimeError`. The `_patched_sleep` function is `async def`, so `raise StopIteration("backtest complete")` becomes `RuntimeError: coroutine raised StopIteration`. The `except StopIteration` on line 149 never fires, meaning `asyncio.sleep` is never restored to its original. Every test or process that calls `asyncio.sleep` after a failed backtest run will hit the patched version.

**Fix:** Replace with a custom sentinel exception (`_BacktestDone`).

---

### C2 — Fill-confirmation sleep advances backtest candle cursor
**Files:** [src/backtest/runner.py:127](../src/backtest/runner.py#L127), [src/loop/executor.py:101](../src/loop/executor.py#L101)

During backtesting, `executor.py` calls `await asyncio.sleep(1)` to confirm fill. This is intercepted by `_patched_sleep`, which calls `sim.advance()`. Every trade in a backtest therefore consumes two candles instead of one — one from the loop sleep and one from the fill-confirmation sleep. Backtests with active trading are systematically shorter, and price data is skipped, making backtest results unreliable.

**Fix:** Check `getattr(hyperliquid, 'is_simulation', False)` in executor.py and skip the fill-confirmation sleep in simulation.

---

### C3 — Kelly criterion silently ignores all short trades
**File:** [src/intelligence/kelly.py:44-61](../src/intelligence/kelly.py#L44)

The pairing logic in `_parse_trade_returns` treats `action="buy"` as "open long" and `action="sell"` as "close long". However, the executor also writes `action="sell"` to open a short position. A full short cycle is:
1. `action="sell"` (open short) — matched against empty `pending`, silently dropped
2. `action="buy"` (close short) — stored in `pending`, never paired

All short trades are invisible to Kelly. If the bot runs losing shorts alongside winning longs, Kelly will compute an overconfident fraction and over-size real positions.

**Fix:** Persist `is_long` in diary entries (already in `active_trades`) and use it to distinguish open/close in the pairing logic.

---

## Important — Fix Before Testnet

### I1 — Force-close removal not immediately persisted to DB
**File:** [src/loop/runner.py:131-173](../src/loop/runner.py#L131)

The force-close block removes trades from `active_trades` in-memory, but `save_all_active_trades` is not called until much later in the cycle (after reconcile). If any exception occurs in between, the DB still holds the removed trade. On restart, the ghost trade reloads and is double-counted in `active_trades`.

**Fix:** Call `save_all_active_trades` immediately after each successful force-close removal.

---

### I2 — Mixed naive/UTC-aware datetimes in same trade record
**File:** [src/loop/executor.py:150,174,182](../src/loop/executor.py#L150)

Three `datetime.now()` calls exist in executor.py:
- Line 150 (`opened_at` in `active_trades` dict): **naive** — no timezone
- Line 174 (`opened_at` in diary entry): **UTC-aware**
- Line 182 (hold diary `timestamp`): **naive**

The `active_trades` entry stored in the DB has a naive `opened_at` while the diary entry for the same trade has a UTC-aware `opened_at`. Downstream parsing or comparison will behave inconsistently.

**Fix:** Replace all three with `datetime.now(timezone.utc).isoformat()`.

---

### I3 — Sequential price fetches per position; no try/except at call site
**Files:** [src/loop/state_builder.py:27](../src/loop/state_builder.py#L27), [src/loop/runner.py:104](../src/loop/runner.py#L104)

`state_builder.py` fetches prices for each open position sequentially in a `for` loop. If any call fails, the exception propagates uncaught through `runner.py` and crashes the entire cycle — force-closes cannot execute during that downtime. With 5 open positions, this is also 5 sequential network calls per cycle instead of one `asyncio.gather`.

**Fix:** (1) Wrap `build_account_state` in `runner.py` with a `try/except` fallback. (2) Use `asyncio.gather` for per-position price fetches in `state_builder.py`.

---

### I4 — Kelly replaces LLM allocation instead of capping it
**File:** [src/loop/executor.py:77-80](../src/loop/executor.py#L77)

`kelly_size_usd` returns one dollar figure applied identically to every asset in a cycle. If the LLM assigns `allocation_usd=200` to BTC (high conviction) and `allocation_usd=50` to ETH (low conviction), both are replaced with the same Kelly figure. The LLM's per-asset conviction signals are discarded.

**Fix:** Use Kelly as a cap, not a replacement: `alloc_usd = min(alloc_usd, kelly_usd)`.

---

### I5 — `db_path` derivation corrupts directory name
**File:** [src/loop/runner.py:68](../src/loop/runner.py#L68)

```python
db_path = diary_path.replace(".jsonl", ".db").replace("diary", "state")
```

`str.replace` replaces all occurrences. If the path is `/data/diary_archive/diary.jsonl`, it becomes `/data/state_archive/state.db` — the directory component is mutated. If that directory doesn't exist, `aiosqlite.connect` fails on startup.

**Fix:** Apply the rename only to the filename component using `pathlib.Path`.

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
