"""Kelly criterion position sizing — computes mathematically optimal trade sizes."""

import json
import os


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Return the Kelly fraction f* = (p*b - q) / b.

    Args:
        win_rate: fraction of winning trades (0–1)
        avg_win:  average return on winning trades (positive %)
        avg_loss: average loss on losing trades (positive %)

    Returns fraction in [0, 1]; 0 if Kelly is negative (bet nothing).
    """
    if avg_loss <= 0 or win_rate <= 0:
        return 0.0
    b = avg_win / avg_loss  # win-to-loss ratio
    q = 1.0 - win_rate
    f = (win_rate * b - q) / b
    return max(0.0, min(1.0, f))


def _parse_trade_returns(diary_path: str, window: int) -> list[float]:
    """Parse diary.jsonl and return per-trade return percentages from paired fills."""
    if not os.path.exists(diary_path):
        return []
    entries = []
    try:
        with open(diary_path) as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                    if e.get("action") in ("buy", "sell", "risk_force_close"):
                        entries.append(e)
                except Exception:
                    continue
    except Exception:
        return []

    pending: dict[str, dict] = {}
    returns: list[float] = []
    for entry in entries:
        asset = entry.get("asset", "")
        action = entry.get("action")
        is_long = entry.get("is_long", True)  # default True for legacy entries

        if action in ("buy", "sell") and is_long == (action == "buy"):
            # Opening a position: buy=open-long, sell=open-short
            pending[asset] = entry
        elif action in ("buy", "sell") and is_long != (action == "buy"):
            # Closing a position: sell=close-long, buy=close-short
            open_entry = pending.pop(asset, None)
            if open_entry:
                entry_px = float(open_entry.get("entry_price") or 0)
                exit_px = float(entry.get("entry_price") or 0)
                if entry_px > 0 and exit_px > 0:
                    if open_entry.get("is_long", True):
                        ret = (exit_px - entry_px) / entry_px * 100
                    else:
                        ret = (entry_px - exit_px) / entry_px * 100
                    returns.append(ret)
        elif action == "risk_force_close":
            pending.pop(asset, None)
            loss_pct = entry.get("loss_pct")
            if loss_pct is not None:
                returns.append(-abs(float(loss_pct)))

    return returns[-window:]


def kelly_size_usd(
    diary_path: str,
    balance: float,
    max_position_usd: float,
    window: int = 30,
    min_trades: int = 10,
) -> float | None:
    """Return Kelly-sized position in USD, or None if insufficient history.

    Uses half-Kelly (f*/2) for safety. Always capped at max_position_usd.

    Args:
        diary_path:      path to diary.jsonl
        balance:         current account balance in USD
        max_position_usd: hard cap from risk manager
        window:          number of recent trades to use
        min_trades:      minimum trades required before Kelly activates

    Returns dollar position size, or None to fall back to LLM allocation.
    """
    returns = _parse_trade_returns(diary_path, window)
    if len(returns) < min_trades:
        return None

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    win_rate = len(wins) / len(returns)
    avg_win = sum(wins) / len(wins) if wins else 0.01
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.01

    f = kelly_fraction(win_rate, avg_win, avg_loss)
    if f <= 0:
        return None  # Kelly says don't bet; fall back to LLM allocation
    half_kelly = f / 2.0
    size = half_kelly * balance
    return min(size, max_position_usd)
