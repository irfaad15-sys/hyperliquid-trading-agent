# 11 — Known Gaps and Caveats

> Read this before going live. Honest. Complete. No sugarcoating.

Code reviewed on 2026-04-26. Findings categorized as **Critical**, **High**, **Medium**, **Low**.

---

## The bottom line

**All 4 pre-live critical bugs are now FIXED (commit `ed46d55`, 2026-04-28):**

| ID | Summary | Status |
|----|---------|--------|
| **C3** | Force-close opens opposite-side position | ✅ FIXED — `place_close_order` (reduce-only via `market_close`) |
| **C5** | TP/SL not validated against current price direction | ✅ FIXED — wrong-side TP nullified; rejects if price = 0 |
| **C6** | Stale price used for sizing + SL after LLM latency | ✅ FIXED — fresh price re-fetched immediately before sizing |
| **C2** | Balance reserve check uses withdrawable balance, not account_value | ✅ FIXED — `check_balance_reserve` now compares `account_value` |

The codebase is now ready for testnet validation. See the order of operations at the bottom of this file.

---

## Structural risk: this bot has no proven edge

Before even getting to bugs — the fundamental truth about this bot:

**Claude is not a trading oracle.** It has no special insight into future prices. When it says "BTC 4h EMA20 above EMA50, positive MACD, going long" — that reasoning is coherent, plausible, and statistically meaningless as a predictor of BTC's next move.

Markets are extremely hard to predict. Professional hedge funds with teams of PhDs and proprietary data still frequently underperform. An LLM making decisions from public indicator data has no structural edge over a coin flip on any given trade.

**What this bot does well:**
- Applies consistent position sizing and stop-losses (when the risk manager is bug-free)
- Doesn't let emotion override rules
- Logs everything for analysis
- Acts as an excellent learning tool for understanding trading mechanics

**What it doesn't do:**
- Guarantee profit
- Backtest
- Adapt to market regime changes
- Access news, order book depth, on-chain data, sentiment

Run it for what it is — a learning experiment with automated risk management — not as an income stream.

---

## Critical bugs — ALL FIXED in commit `ed46d55` (2026-04-28)

### C3 — Force-close is not reduce-only ✅ FIXED

**Fix applied**: Added `place_close_order(asset, is_long, size)` to `hyperliquid_api.py` using `exchange.market_close()` (reduce-only). Runner now calls `cancel_all_orders` first, then `place_close_order`. See [src/trading/hyperliquid_api.py](../src/trading/hyperliquid_api.py) and [src/loop/runner.py](../src/loop/runner.py).

Also fixed H4 (duplicate force-close): `_force_close_attempted` set prevents re-sending a close order if the previous one is still pending fill.

---

### C5 — TP/SL direction not validated ✅ FIXED

**Fix applied**: `validate_trade` in [src/risk_manager.py](../src/risk_manager.py) now:
1. Rejects the trade outright if `current_price <= 0`
2. Validates TP direction — wrong-side TP is nullified with a warning (not traded)
3. Auto-SL computed from `current_price` directly (no `$1` fallback)

---

### C6 — Price is stale by the time it's used for sizing ✅ FIXED

**Fix applied**: `executor.py` re-fetches a fresh price immediately after risk validation, before computing `amount`. If the fetch fails or returns 0, the trade is skipped. If price moved >5% during LLM latency, a warning is logged. See [src/loop/executor.py](../src/loop/executor.py).

---

### C2 — Balance reserve check uses withdrawable balance ✅ FIXED

**Fix applied**: `check_balance_reserve(account_value, initial_account_value)` now compares total account value (including open-position collateral) against the reserve floor. Open positions no longer cause false blocks. See [src/risk_manager.py](../src/risk_manager.py).

---

## High severity — ALL FIXED in commit `ed46d55` (2026-04-28)

### H1 — Total value strips negative PnL ✅ FIXED

`hyperliquid_api.py` now uses signed PnL: `total_value = balance + sum(p.get("pnl", 0.0) for p in enriched_positions)`. Circuit breaker fires on schedule even on losing days.

### H2 — Fill confirmation window too wide ✅ FIXED

`executor.py` records `order_ts_ms = time.time() * 1000` immediately before placing the order. Fill confirmation now checks `fill_time >= order_ts_ms` (not a fixed 2-second window), so only fills from this specific order are counted.

### H4 — Force-close repeats every cycle ✅ FIXED

`_force_close_attempted` set in `runner.py` tracks assets where a close order was sent. Subsequent cycles skip the asset until its position disappears from live state.

### H5 — Diary entry not written if TP/SL fails ✅ FIXED

`executor.py` writes the diary entry immediately after the entry order succeeds, before TP/SL placement. TP/SL OIDs are part of the same entry. A TP/SL network failure no longer loses the trade record.

---

## Medium severity

### M4 — Cooldown not machine-enforced (LLM can churn every cycle)

The system prompt tells Claude to self-impose a 3-bar cooldown after direction changes. There is no code that enforces this. A jittery market produces a jittery LLM which produces excessive trading — burning API fees and slippage.

**Real cost**: at 5-min intervals, a bot flipping BTC buy/sell every cycle pays ~0.05% per trade in fees × 288 trades/day = 14.4% daily fee churn. Your $100 is effectively losing ~$14/day to fees before any market loss.

**Fix**: Add `last_action_time[asset]` tracking in `main.py`; block direction changes within 3 intervals unless force-close triggers.

### M1 — TP/SL order errors silently ignored

If `exchange.order()` returns an error status for a TP placement, `extract_oids` returns `[]`, `tp_oid = None`, and the log says "TP placed BTC at 73000.0" — but the TP was never actually placed.

**Fix**: Check for `error` keys in the order response statuses and log/raise.

### M6 — Log files grow without bound

`prompts.log` and `llm_requests.log` are never rotated. A week of 5-min intervals with full context dumps = 500MB–1GB. Running out of disk space crashes the bot.

**Workaround**: trim manually (see [10-OPERATIONAL-RUNBOOK.md](10-OPERATIONAL-RUNBOOK.md)). Long-term fix: add `logging.handlers.RotatingFileHandler`.

---

## Low severity

### L1 — README defaults don't match code

The README is the first thing a user reads. It lists safety defaults that are significantly looser than what it states. See [04-RISK-MANAGEMENT.md](04-RISK-MANAGEMENT.md) for the full table.

**Fix**: update README to match `.env.example` and code defaults, or note that `.env.example` is the authoritative default source.

### L7 — `clear_terminal()` runs `os.system('clear')` on startup

Fine locally. In Docker or when collecting output with `nohup`, this creates a garbage escape code in the logs.

---

## Missing features (not bugs, but worth knowing)

1. **No notification/alert system** — the bot doesn't tell you when something important happens. You have to actively check.

2. **No kill switch beyond Ctrl+C** — there's no "stop trading, close all positions" command. You have to stop the bot and manually close on the exchange.

3. **No multi-instance protection** — running two copies of the bot simultaneously results in duplicate orders.

4. **No backtest** — there's no way to test a new strategy configuration against historical data before running it live.

5. **No Anthropic spend limit integration** — the bot doesn't know or care how much you're spending on Claude API. Set limits in the Anthropic console separately.

6. **No persistent state across restarts** — `active_trades` is in-memory only. A restart loses the bot's knowledge of what it intended. It recovers via reconciliation but won't know the original exit plan for pre-restart positions.

7. **No position size update** — if you want to add to an existing position or reduce it partially, the bot currently opens new positions or closes full ones.

---

## Should you run this with $100?

**Yes — all blocking bugs are now fixed. The bot is ready for testnet.**

The risk manager is architecturally sound and the critical/high bugs are resolved. With the conservative settings from [04-RISK-MANAGEMENT.md](04-RISK-MANAGEMENT.md) and after a clean testnet run, a $100 live run is an acceptable learning investment.

The order of operations:
1. Run testnet for 1–3 days
2. Confirm fills, force-closes, and stop-losses behave correctly in logs
3. Then go live with $100 at conservative settings
4. Watch it daily for 2 weeks
5. Evaluate and decide next steps
