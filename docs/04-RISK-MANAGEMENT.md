# 04 — Risk Management

> Every safety guard, what it does, what value it actually has in code, and what the README says it has. **Spoiler: the README and the code disagree.**

---

## The core principle

All risk checks are enforced in [src/risk_manager.py](../src/risk_manager.py), **not** in the LLM prompt. The LLM is informed of the limits but cannot override them. Every trade flows through `validate_trade` before order placement. (With one important exception — the force-close path, see **C3** below.)

---

## The README vs. code defaults

This repo previously had a mismatch between the README and the code defaults. The README has now been updated to match `src/config_loader.py` and `.env.example`.

Always verify your actual `.env` values before running, because the bot uses whatever values are present in your environment at startup.

> Note: the risk guidance in this docs suite remains conservative. For a safe first $100 run, prefer tighter values than the code defaults.

---

## Every guard, explained

### 1. Force-close losing positions

**File**: [risk_manager.py:144–183](../src/risk_manager.py#L144-L183) → called from [main.py:135](../src/main.py#L135)

**Trigger**: any position whose unrealized loss ≥ `MAX_LOSS_PER_POSITION_PCT` of its own notional.

```python
notional = abs(size) * entry_px
loss_pct = abs(pnl / notional) * 100 if pnl < 0 else 0
if loss_pct >= max_loss_per_position_pct:
    # close it
```

**What "20% loss" actually means**: the position has lost 20% of its **own** notional (entry size × entry price), not 20% of your portfolio. With 10x leverage, a 20% notional loss = a 200% loss on collateral, which means the position is already past liquidation. So practically this fires at the price-move threshold equivalent to roughly:

| Leverage | Force-close trigger price move |
|----------|------------------------------|
| 1x       | ~20%                         |
| 5x       | ~4%                          |
| 10x      | ~2%                          |

So at 10x leverage, the force-close fires at a 2% adverse move. Fast.

**Critical bug — C3**: the close uses `place_sell_order` / `place_buy_order` which call `market_open` (not reduce-only). If a TP/SL has filled between snapshot and close, this order opens an opposite-side position. **Must be fixed before real money.** See [11-KNOWN-GAPS-AND-CAVEATS.md](11-KNOWN-GAPS-AND-CAVEATS.md).

### 2. Daily drawdown circuit breaker

**File**: [risk_manager.py:88–102](../src/risk_manager.py#L88-L102)

**Behavior**: tracks the highest `account_value` seen today (UTC day). If account drops > `DAILY_LOSS_CIRCUIT_BREAKER_PCT` from that high, **block all new trades** until tomorrow.

Resets at UTC midnight. Existing positions are **not** closed by this check — only new trades are blocked.

**What it does NOT do**:
- Close positions (only blocks new ones).
- Trigger immediately at startup (the initial high watermark = first observed `account_value`).
- Account for cumulative drawdown across days.

**Real-money implication**: with default 25%, you can lose 24.99% in a day before this fires. With $100 that's a $25 loss. We recommend setting to **10%** for first run.

### 3. Balance reserve

**File**: [risk_manager.py:112–122](../src/risk_manager.py#L112-L122)

**Behavior**: if `balance < initial_balance * MIN_BALANCE_RESERVE_PCT / 100`, block new trades.

**Bug — C2**: this uses `balance` (withdrawable USDC), not `account_value`. On a perp account with collateral locked in open positions, `balance` can be near zero while `account_value` is fine. Result: any open position likely trips this guard, silently disabling new trades.

**Workaround**: set `MIN_BALANCE_RESERVE_PCT` low (e.g., 5) for testnet, or fix the bug in code.

### 4. Position size cap

**File**: [risk_manager.py:48–58](../src/risk_manager.py#L48-L58) and the **capping behavior** at [risk_manager.py:233–243](../src/risk_manager.py#L233-L243)

**Behavior**: caps any single trade allocation at `account_value × MAX_POSITION_PCT / 100`.

This is a **cap, not a reject**. If the LLM asks for $50 on a $100 account at 20% cap, it becomes $20 silently. If it asks for $10,000, it becomes $20.

**Why this is risky**: a buggy LLM that always returns `allocation_usd: 99999` will always trade at the cap. There's no upstream sanity check. Flagged as **C4**.

**Mitigation**: add `MAX_POSITION_PCT=10` to your `.env`. With $100, that's a $10 ceiling per trade.

### 5. Total exposure cap

**File**: [risk_manager.py:60–75](../src/risk_manager.py#L60-L75)

**Behavior**: sum of `(qty × entry_px)` across all open positions, plus the new trade, cannot exceed `account_value × MAX_TOTAL_EXPOSURE_PCT / 100`.

If exceeded, the new trade is **rejected** (not capped).

With default 80% on $100, you can hold $80 of total notional. With 10x leverage that means... still $80 notional, since it's bounded by exposure not leverage. Good.

### 6. Leverage cap

**File**: [risk_manager.py:77–86](../src/risk_manager.py#L77-L86)

**Behavior**: rejects trade if `alloc_usd / balance > MAX_LEVERAGE`.

With $100 balance, max alloc per trade = $1000 (10x). Note this divides by `balance`, not `account_value`, so as positions consume collateral, available leverage budget shrinks.

### 7. Concurrent positions limit

**File**: [risk_manager.py:104–110](../src/risk_manager.py#L104-L110)

**Behavior**: if already holding `MAX_CONCURRENT_POSITIONS` (default 10) open positions, reject new ones.

With $100 capital and the default of 10 positions, each is $10 — exactly at Hyperliquid's $10 minimum order. Any cap below that means trades will be auto-bumped to $11 minimum, which can violate the position-size cap. Edge cases like this are why you should run testnet first.

### 8. Mandatory stop-loss

**File**: [risk_manager.py:128–138](../src/risk_manager.py#L128-L138)

**Behavior**: if the LLM doesn't supply `sl_price`, auto-set it at `MANDATORY_SL_PCT` from entry.

```python
sl_distance = entry_price * (mandatory_sl_pct / 100.0)
if is_buy:  return entry_price - sl_distance
else:       return entry_price + sl_distance
```

**Bug — fallback default**: at [risk_manager.py:266](../src/risk_manager.py#L266), if `current_price` ever comes through as 0 (e.g., a HIP-3 lookup miss), `entry_price` falls back to `1.0`, and SL is computed as `0.95`. For a $70,000 BTC position, an SL at $0.95 will literally never trigger — effectively no stop. Flagged in **C5**.

**Mitigation**: stick to native crypto perps (BTC, ETH, SOL) for first run. Avoid HIP-3 (xyz:GOLD, xyz:TSLA) until you've verified `get_current_price` returns sane values.

### 9. TP/SL sign validation — **MISSING**

The system prompt tells Claude:
- BUY: `tp_price > current_price`, `sl_price < current_price`
- SELL: `tp_price < current_price`, `sl_price > current_price`

But **the risk manager does not check this**. If Claude returns a long with `tp_price < current_price`, Hyperliquid receives a take-profit trigger order that fires immediately at market, closing the position the moment it opens. Same for SL on the wrong side. The trade locks in a loss equal to slippage + fees.

This is **C5** — must fix before mainnet.

### 10. Cooldown — **NOT ENFORCED**

The system prompt tells Claude to self-impose a 3-bar cooldown after any direction change. There's **no machine-side enforcement**. A jittery LLM can flip every cycle. Flagged as **M7**.

---

## Order of checks in `validate_trade`

Read [risk_manager.py:189–274](../src/risk_manager.py#L189-L274). The order matters:

```
hold? -> return True (no checks)
allocation <= 0? -> reject
allocation < $11? -> bump to $11 (Hyperliquid min)
daily drawdown breached? -> reject
balance reserve breached? -> reject  [C2 bug here]
position size > cap? -> CAP, not reject
total exposure breached? -> reject
leverage breached? -> reject
concurrent positions full? -> reject
sl_price missing? -> auto-set
return True
```

Things to notice:
- "Position size cap" silently rewrites the trade. Other checks reject. Inconsistent.
- "Auto-set SL" runs after capping but uses `current_price` from the trade dict, which (a) may be 0 (bug fallback to $1) and (b) is stale by the time the trade is placed (C6).
- TP/SL sign validation is absent.

---

## Risk *not* covered by `RiskManager`

A non-exhaustive list of things the risk manager doesn't catch:

1. **API key compromise** — agent wallet leak. Hyperliquid's two-wallet design helps but doesn't stop trading losses.
2. **Stale prices** — sized off a price 30s old (C6).
3. **Wrong-side TP/SL** — locks in losses (C5).
4. **Force-close opening opposite position** (C3).
5. **Anthropic API outage** — bot returns "hold" for all, no panic state.
6. **Hyperliquid API outage** — bot retries 3x with backoff, then logs and moves on.
7. **Network partition** — same as above.
8. **Liquidation due to funding** — funding accrues continuously; if a position sits in high-funding state, collateral shrinks. The 20% force-close should catch most of this, but funding-driven liquidations during the bot being offline can wipe positions.
9. **Multiple bot instances running** — if you accidentally `python -m src.main` twice, both bots place orders. Nothing stops this.
10. **Claude returning hallucinated assets** — the bot does check `asset in args.assets`, but if Claude returns `BTC` correctly while the LLM is actually thinking about `ETH`, the trade goes through under the wrong label.

---

## Recommended starting risk profile for $100

After reading the above, I'd recommend running with these env values for your first real-money week:

```bash
# Tight risk limits for first $100 run
MAX_POSITION_PCT=10                 # $10 max per trade
MAX_LOSS_PER_POSITION_PCT=15        # close at 15%, before liquidation buffer
MAX_LEVERAGE=3                      # cap at 3x — deeper buffer to liquidation
MAX_TOTAL_EXPOSURE_PCT=30           # $30 total notional max
DAILY_LOSS_CIRCUIT_BREAKER_PCT=10   # stop after 10% daily loss = $10
MANDATORY_SL_PCT=3                  # tighter default SL
MAX_CONCURRENT_POSITIONS=3          # focus, don't fragment $100 across 10 positions
MIN_BALANCE_RESERVE_PCT=10          # but watch C2 bug — may auto-disable trading
```

Why these:
- **3x leverage** is generous enough to allow real upside while keeping liquidation distance ~30%+ — a buffer larger than typical daily volatility for BTC/ETH.
- **10% position max ($10)** means a complete loss on one trade is 10% of account.
- **3 concurrent positions** keeps each trade meaningful at ~$10 minimum order size.
- **10% daily circuit breaker** stops trading after a $10 loss day. You will sleep.

Adjust upward only after you've watched it work for a week and read the diary daily.
