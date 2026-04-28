# Intelligence + Architecture Plan
**Date:** 2026-04-27
**Status:** Approved — pending implementation

---

## 1. Audit Findings (post M1/M2/M3)

### 1.1 Confirmed Bugs (must fix before new features)

#### H1 — `total_return_pct` uninitialized before loop
**File:** `src/main.py:115`
**Severity:** Medium — potential NameError on error-recovery paths
**Description:** `total_return_pct` is guarded by `if invocation_count > 1 else 0.0` at line 115, but is never initialized before the `while True` loop. If the loop body raises between lines 108 and 127 on the first iteration, any subsequent iteration that reaches line 115 with `invocation_count > 1` will raise `NameError: name 'total_return_pct' is not defined`.
**Fix:** Add `total_return_pct = 0.0` to the pre-loop initialization block alongside `invocation_count = 0`.

#### H2 — `state['positions']` direct dict access (4 missed instances)
**File:** `src/main.py:130, 146, 442`
**Severity:** Major — KeyError crash if Hyperliquid API omits the field
**Description:** M1 fixed line 110 but missed these instances. The `state` dict is returned by `get_user_state()`, which can return partial data.
- Line 130: `for pos_wrap in state['positions']:`
- Line 146: `risk_mgr.check_losing_positions(state['positions'])`
- Line 442: `len([p for p in state['positions'] if ...])`
**Fix:** Replace all three with `state.get('positions', [])`.

#### H3 — `state['balance']` direct dict access (2 missed instances)
**File:** `src/main.py:263, 441`
**Severity:** Major — KeyError crash if balance field is absent
**Description:** M1 fixed the main balance read but missed the logging/dashboard paths.
- Line 263: `"balance": round_or_none(state['balance'], 2)` (dashboard dict)
- Line 441: `"balance": round_or_none(state['balance'], 2)` (cycle_log dict)
**Fix:** Replace both with `state.get('balance', 0)`.

#### H4 — `output["exit_plan"]` direct dict access (2 instances)
**File:** `src/main.py:525, 552`
**Severity:** Major — KeyError if LLM omits `exit_plan` field
**Description:** `decision_maker.py` calls `item.setdefault("exit_plan", "")` for the sanitizer path, but if that path is skipped or the LLM output is missing the field, direct access crashes.
- Line 525: `"exit_plan": output["exit_plan"]` (trade_log append)
- Line 552: `"exit_plan": output["exit_plan"]` (active_trades append)
**Fix:** Replace both with `output.get("exit_plan", "")`.

---

### 1.2 Structural Holes

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| S1 | No test infrastructure | entire codebase | Cannot safely refactor or verify bug fixes |
| S2 | 681-line monolith | `src/main.py` | Hard to reason about, edit, or test in isolation |
| S3 | No state persistence | `active_trades` list in memory | All open trade tracking lost on restart |
| S4 | Dead code — `recent_events` deque | `main.py:80` | Defined but never populated; `add_event()` only calls `logging.info()` |
| S5 | No backtesting | — | Cannot validate strategy changes before live deployment |
| S6 | No post-trade learning | — | LLM context has no feedback on past trade outcomes |
| S7 | Naive Sharpe ratio | `calculate_sharpe()` | No risk-free rate, no annualization, no min-sample guard |

---

## 2. Decomposed Plan — C (Intelligence) + E (Architecture)

Each sub-project is scoped to be independently implementable and testable.

### E1 — Decompose main.py (Architecture)
**Goal:** Split the 681-line monolith into focused modules.
**Proposed module split:**
```
src/
  main.py              # ~80 lines: arg parse, init, scheduler
  loop/
    runner.py          # run_loop() — main while True
    state_builder.py   # fetch + normalize account state
    dashboard.py       # build dashboard dict for API
    executor.py        # trade execution + TP/SL placement
    reconciler.py      # fill detection + active_trades sync
  risk/
    manager.py         # (already exists as risk_manager.py)
```
**Acceptance:** Each module has ≤200 lines; `main.py` is ≤100 lines; existing behavior unchanged.

### E2 — State persistence with SQLite
**Goal:** Survive restarts without losing `active_trades` and trade log.
**Proposed design:**
- New `src/storage/db.py` wrapping SQLite via `aiosqlite`
- Tables: `active_trades`, `trade_log`, `cycle_log`
- `active_trades` loaded from DB at startup; written after every change
- Existing `diary.jsonl` and `decisions.jsonl` remain as human-readable audit logs
**Dependency:** `aiosqlite` (pure-Python, no new binary dependencies)
**Acceptance:** Agent restarts with same active_trades as before crash.

### E3 — Test infrastructure
**Goal:** pytest suite covering the critical paths that have crashed in production.
**Scope (phase 1):**
- Unit tests for `RiskManager` (force-close thresholds, circuit breaker)
- Unit tests for `config_loader` (missing envvars, invalid types)
- Integration tests for `state_builder` using a mocked `HyperliquidAPI`
- Smoke test: full loop iteration against recorded API fixture
**Tooling:** `pytest`, `pytest-asyncio`, `pytest-mock` — all pure-Python
**Acceptance:** `pytest` runs cleanly with ≥80% line coverage on `risk_manager.py` and `config_loader.py`.

### C1 — Backtesting framework
**Goal:** Replay historical OHLCV data through the LLM decision loop in simulation mode.
**Proposed design:**
- `src/backtest/runner.py`: loads OHLCV from CSV or Hyperliquid history API
- Replaces `HyperliquidAPI` with a `SimulatedAPI` that returns historical prices
- Produces a performance report: total return, Sharpe, max drawdown, win rate
**Acceptance:** Can run a 30-day backtest on BTC/ETH and produce a report without live API calls.

### C2 — Kelly criterion position sizing
**Goal:** Replace fixed `allocation_usd` from LLM with Kelly-optimal sizing.
**Proposed design:**
- New `src/intelligence/kelly.py`: `kelly_fraction(win_rate, avg_win, avg_loss)` → fraction
- Uses trade_log (or DB once E2 ships) to compute rolling 30-trade win stats
- Applies a half-Kelly cap for safety: `position_usd = min(kelly * balance, max_position_usd)`
- LLM still signals direction (buy/sell/hold); Kelly determines size
**Acceptance:** On 50-trade history, sizing is within ±20% of theoretical Kelly; never exceeds `MAX_POSITION_PCT`.

### C3 — Post-trade learning loop
**Goal:** Feed past trade outcomes back into the LLM prompt so it can self-correct.
**Proposed design:**
- After each loop, append last 5 closed trades (entry, exit, P&L, reasoning) to prompt context
- Format: JSONL diary entries filtered by `action in ("closed", "risk_force_close")`
- Gate behind `LEARNING_WINDOW=5` env var (default 5 trades)
- Depends on E2 (persistent trade log) for full reliability; falls back to in-memory diary otherwise
**Acceptance:** LLM prompt includes last-N closed trade outcomes; verified via `LOG_FULL_PROMPT=true`.

### C4 — Prompt engineering pass
**Goal:** Improve signal quality and reduce LLM refusals/hallucinations.
**Scope:**
- Add explicit output schema (JSON Schema) to system prompt
- Add examples of correct output format (few-shot)
- Separate market analysis prompt from decision prompt (two-step)
- Add asset-specific context blocks (crypto vs commodity vs index)
**Acceptance:** LLM JSON parse failures drop by ≥50% over 48h run; measured via `decisions.jsonl` parse error rate.

---

## 3. Recommended Implementation Sequence

```
Priority 1 — Unblock safety (this week)
  H1 fix  →  H2 fix  →  H3 fix  →  H4 fix
  (all in src/main.py, ~20 lines total)

Priority 2 — Structural foundation (next 2 weeks)
  E1 (decompose main.py)
  E3 (test infrastructure)      ← depends on E1 for clean module boundaries

Priority 3 — Intelligence layer (2–4 weeks)
  C3 (post-trade learning)      ← quick win, no new infra needed
  C1 (backtesting)              ← enables safe validation of C2/C4
  C2 (Kelly sizing)             ← validated by C1
  C4 (prompt engineering)       ← measured against baseline

Priority 4 — Persistence (after C3/C4 stable)
  E2 (SQLite state)             ← C3 degrades gracefully without it, but E2 makes it reliable
```

---

## 4. Out of Scope (deferred to future phases)

- Full Observability dashboard (D) — email alerting already covers the critical path
- Multi-exchange support
- Order book / level 2 data integration
- Autonomous strategy selection
