# 07 — Configuration Reference

> Every environment variable the bot reads. What it does, valid values, default, and what changes if you tune it.

All variables go in `.env` in the project root (copy from `.env.example`). The format is:

```bash
VARIABLE_NAME=value
# Comments work like this
```

---

## Required variables — the bot crashes without these

### `ANTHROPIC_API_KEY`

Your Claude API key from [console.anthropic.com](https://console.anthropic.com).

```bash
ANTHROPIC_API_KEY=sk-ant-api03-...
```

Get it from: Console → API Keys → Create Key.

**Important**: Set a monthly spend limit in the console. With 5-min intervals and Sonnet-4, expect $3–10/day. A $30/month cap gives you ~3 days of runtime before it cuts off — adjust as needed.

---

### `HYPERLIQUID_PRIVATE_KEY`

The **agent wallet's** private key. This is the wallet that *signs* trades, not the one that holds your funds.

```bash
HYPERLIQUID_PRIVATE_KEY=0xabc123...
```

- Must start with `0x`.
- This is the key you generated/exported from your agent wallet (MetaMask, or the Hyperliquid "Create API Wallet" button).
- **Never use your main wallet's key here.** It's not needed and is a security risk.
- If compromised, an attacker can trade but cannot withdraw your USDC (that requires the main wallet).

---

### `HYPERLIQUID_VAULT_ADDRESS`

The **main wallet's** Ethereum address. This is where your USDC actually sits.

```bash
HYPERLIQUID_VAULT_ADDRESS=0xdef456...
```

- Must start with `0x`, 42 characters total.
- This is **not** a private key — it's just a public address.
- The bot queries account state for this address and places trades on its behalf.
- If you leave this blank, the bot uses the agent wallet's address instead (only safe if they're the same wallet, i.e., you're not using separate agent wallets).

---

### `ASSETS`

Space-separated list of assets to trade.

```bash
ASSETS="BTC ETH SOL"
# or with HIP-3 assets:
ASSETS="BTC ETH xyz:GOLD xyz:TSLA"
```

- Crypto perps: just the ticker (`BTC`, `ETH`, `SOL`, etc.)
- HIP-3 assets: `dex:ticker` format (`xyz:GOLD`, `xyz:TSLA`, `xyz:SP500`, etc.)
- All must be active Hyperliquid perp markets. Check [app.hyperliquid.xyz](https://app.hyperliquid.xyz) for the full list.
- More assets = longer prompt = higher API cost per cycle = more Claude calls.
- **For first run: stick to 2–3 high-liquidity crypto assets** (BTC, ETH, SOL). Avoid HIP-3 until you understand the system.

---

### `INTERVAL`

How often the loop runs.

```bash
INTERVAL=5m   # 5 minutes
INTERVAL=1h   # 1 hour
INTERVAL=4h   # 4 hours
```

Valid suffixes: `m` (minutes), `h` (hours), `d` (days).

**Trade-offs**:

| Interval | API calls/day | Cost/day (approx) | Bot behavior |
|----------|---------------|-------------------|-------------|
| 5m       | ~288           | $5–12             | Very active, many decisions |
| 15m      | ~96            | $1.50–4           | Moderate |
| 1h       | ~24            | $0.40–1           | Low cost, slower reactions |
| 4h       | ~6             | $0.10–0.25        | Very slow, swing trading style |

**For first run**: `INTERVAL=15m` is a good balance — active enough to catch moves, cheap enough not to drain your Anthropic credit fast.

---

## Risk management variables

See [04-RISK-MANAGEMENT.md](04-RISK-MANAGEMENT.md) for detailed explanation of each guard.

### `MAX_POSITION_PCT`
**Default in code**: `20`

Max single trade as a percent of account value. Excess allocation is capped (not rejected).

```bash
MAX_POSITION_PCT=10    # $10 max on $100 account — recommended for first run
```

---

### `MAX_LOSS_PER_POSITION_PCT`
**Default**: `20`

Force-close a position when its unrealized loss reaches this % of its own notional. With leverage, this fires at a smaller price move (see doc 04 table).

```bash
MAX_LOSS_PER_POSITION_PCT=15   # tighter — recommended for first run
```

---

### `MAX_LEVERAGE`
**Default**: `10`

Hard cap on `alloc_usd / balance`. Trades exceeding this are rejected.

```bash
MAX_LEVERAGE=3    # conservative — for first run
```

---

### `MAX_TOTAL_EXPOSURE_PCT`
**Default in code**: `80`

Max sum of all position notionals as % of account value. New trades that would exceed this are rejected.

```bash
MAX_TOTAL_EXPOSURE_PCT=30   # conservative — recommended for first run
```

---

### `DAILY_LOSS_CIRCUIT_BREAKER_PCT`
**Default in code**: `25`

Stops new trades when account drops this % from today's high watermark. Resets at UTC midnight. Does not close existing positions.

```bash
DAILY_LOSS_CIRCUIT_BREAKER_PCT=10   # stop after 10% daily loss — recommended
```

---

### `MANDATORY_SL_PCT`
**Default**: `5`

Auto-set stop-loss at this % from entry if the LLM doesn't provide one.

```bash
MANDATORY_SL_PCT=3   # tighter default SL — recommended
```

---

### `MAX_CONCURRENT_POSITIONS`
**Default**: `10`

Max number of simultaneously open positions. New trades are rejected when at the limit.

```bash
MAX_CONCURRENT_POSITIONS=3   # focus on fewer trades with $100 — recommended
```

---

### `MIN_BALANCE_RESERVE_PCT`
**Default in code**: `10`

Don't trade if balance falls below this % of initial balance. **Bug C2**: this checks withdrawable balance, not account value — may silently disable trading when collateral is in use.

```bash
MIN_BALANCE_RESERVE_PCT=5    # set low to avoid C2 bug blocking all trades
```

---

## LLM variables

### `LLM_MODEL`
**Default**: `claude-sonnet-4-20250514`

Which Claude model to use. Options as of 2026:

| Model | Speed | Quality | Cost/1M tokens |
|-------|-------|---------|---------------|
| `claude-haiku-4-5-20251001` | Fast | Lower | Cheap |
| `claude-sonnet-4-6` | Medium | Good | Moderate |
| `claude-sonnet-4-20250514` | Medium | Good | Moderate |
| `claude-opus-4-7` | Slow | Highest | Expensive |

**For $100 first run**: stick with the default Sonnet model. Don't use Opus unless you want to spend significantly more on API fees.

```bash
LLM_MODEL=claude-sonnet-4-6
```

---

### `SANITIZE_MODEL`
**Default**: `claude-haiku-4-5-20251001`

Cheap model used to extract valid JSON when the primary model returns malformed output. Default is fine.

---

### `MAX_TOKENS`
**Default**: `4096`

Maximum tokens in Claude's response. With reasoning text + decisions for 3 assets, 4096 is plenty. Only change if you're trading 10+ assets and hitting truncation.

---

### `THINKING_ENABLED`
**Default**: `false`

Enable Claude's extended thinking (longer internal reasoning before answering). Set to `true` only if you want improved decision quality and are OK with:
- 2–5× longer cycle time
- Higher API cost
- More stale prices (C6 bug is amplified)

```bash
THINKING_ENABLED=false   # leave off for first run
```

---

### `THINKING_BUDGET_TOKENS`
**Default**: `10000`

Token budget for thinking mode. Only relevant when `THINKING_ENABLED=true`.

---

### `ENABLE_TOOL_CALLING`
**Default**: `false`

Allow Claude to call `fetch_indicator` during its reasoning. When `true`:
- Claude can request any indicator not already in the prompt
- Adds latency (each tool call = another Hyperliquid API call + processing)
- Costs more tokens

Leave `false` for first run.

---

## Network variables

### `HYPERLIQUID_NETWORK`
**Default**: `mainnet`

```bash
HYPERLIQUID_NETWORK=testnet    # for testnet runs
HYPERLIQUID_NETWORK=mainnet    # for real money
```

This sets the base URL for all Hyperliquid API calls.

---

### `HYPERLIQUID_BASE_URL`
**Default**: (auto-selected based on `HYPERLIQUID_NETWORK`)

Override the Hyperliquid API base URL manually. Leave blank to use the default for your network.

---

### `MNEMONIC`
**Default**: (blank)

Alternative to `HYPERLIQUID_PRIVATE_KEY` — provide a 12/24-word seed phrase instead. Only use this if your wallet setup requires it. Private key is safer (more limited scope).

---

## API server variables

### `API_HOST`
**Default**: `0.0.0.0`

Host the HTTP API listens on. `0.0.0.0` means accessible from any network interface (including external). For local-only: use `127.0.0.1`.

```bash
API_HOST=127.0.0.1   # local only — safer
```

---

### `API_PORT` / `APP_PORT`
**Default**: `3000`

Port for the `/diary` and `/logs` HTTP endpoints.

```bash
API_PORT=3000
```

---

## Recommended `.env` for testnet first run

```bash
# === REQUIRED ===
ANTHROPIC_API_KEY=sk-ant-api03-...
HYPERLIQUID_PRIVATE_KEY=0x...          # your testnet agent wallet key
HYPERLIQUID_VAULT_ADDRESS=0x...        # your testnet main wallet address

# === TRADING ===
ASSETS="BTC ETH SOL"
INTERVAL=15m
LLM_MODEL=claude-sonnet-4-6

# === NETWORK ===
HYPERLIQUID_NETWORK=testnet

# === CONSERVATIVE RISK (for $100 first run) ===
MAX_POSITION_PCT=10
MAX_LOSS_PER_POSITION_PCT=15
MAX_LEVERAGE=3
MAX_TOTAL_EXPOSURE_PCT=30
DAILY_LOSS_CIRCUIT_BREAKER_PCT=10
MANDATORY_SL_PCT=3
MAX_CONCURRENT_POSITIONS=3
MIN_BALANCE_RESERVE_PCT=5

# === OPTIONAL / LEAVE OFF ===
# THINKING_ENABLED=false
# ENABLE_TOOL_CALLING=false
# API_HOST=127.0.0.1
# API_PORT=3000
```

Copy this block into `.env` and fill in the three required values. Everything else has a safe default.
