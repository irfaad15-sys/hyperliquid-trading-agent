"""Backtest runner — replay historical OHLCV through the agent loop in simulation."""

import asyncio
import csv
import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from src.backtest.simulated_api import SimulatedAPI
from src.loop.runner import run_loop


def load_ohlcv_csv(path: str, asset: str) -> list[dict]:
    """Load OHLCV data from a CSV file.

    Expected columns (case-insensitive): timestamp, open, high, low, close, volume
    timestamp may be a Unix ms integer or ISO-8601 string.
    Returns a list of candle dicts with keys: t, o, h, l, c, v
    """
    candles = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        headers = {h.lower().strip(): h for h in (reader.fieldnames or [])}
        for row in reader:
            try:
                t_raw = row.get(headers.get("timestamp", "")) or row.get(headers.get("time", ""), "0")
                try:
                    t = int(t_raw)
                except ValueError:
                    t = int(datetime.fromisoformat(t_raw).timestamp() * 1000)
                candles.append({
                    "t": t,
                    "o": float(row.get(headers.get("open", ""), 0)),
                    "h": float(row.get(headers.get("high", ""), 0)),
                    "l": float(row.get(headers.get("low", ""), 0)),
                    "c": float(row.get(headers.get("close", ""), 0)),
                    "v": float(row.get(headers.get("volume", ""), 0)),
                })
            except Exception:
                continue
    return candles


def _compute_report(initial_balance: float, final_balance: float, fills: list[dict]) -> dict:
    """Compute backtest performance metrics from fill history."""
    total_return_pct = ((final_balance - initial_balance) / initial_balance * 100) if initial_balance else 0.0
    if not fills:
        return {
            "initial_balance": round(initial_balance, 2),
            "final_balance": round(final_balance, 2),
            "total_return_pct": round(total_return_pct, 2),
            "total_trades": 0,
            "win_rate_pct": 0.0,
            "sharpe": 0.0,
        }

    # Naive per-trade PnL from paired fills (buy then sell)
    trade_returns = []
    pending: dict[str, dict] = {}
    for fill in fills:
        asset = fill.get("coin", "")
        is_buy = fill.get("isBuy", True)
        price = float(fill.get("px", 0))
        size = float(fill.get("sz", 0))
        if is_buy:
            pending[asset] = {"price": price, "size": size}
        else:
            entry = pending.pop(asset, None)
            if entry:
                ret = (price - entry["price"]) / entry["price"] * 100
                trade_returns.append(ret)

    sharpe = 0.0
    if len(trade_returns) >= 2:
        mean = sum(trade_returns) / len(trade_returns)
        var = sum((r - mean) ** 2 for r in trade_returns) / len(trade_returns)
        std = math.sqrt(var) if var > 0 else 0
        sharpe = mean / std if std > 0 else 0.0

    return {
        "initial_balance": round(initial_balance, 2),
        "final_balance": round(final_balance, 2),
        "total_return_pct": round(total_return_pct, 2),
        "total_trades": len(fills),
        "win_rate_pct": round(
            sum(1 for r in trade_returns if r > 0) / len(trade_returns) * 100, 1
        ) if trade_returns else 0.0,
        "sharpe": round(sharpe, 3),
    }


class _BacktestDone(Exception):
    pass


async def run_backtest(
    agent,
    risk_mgr,
    ohlcv: dict[str, list[dict]],
    assets: list[str],
    initial_balance: float = 10_000.0,
    candles_per_step: int = 1,
    diary_path: str = "backtest_diary.jsonl",
) -> dict:
    """Run a full backtest and return a performance report dict.

    Args:
        agent: TradingAgent instance (uses real LLM — set LLM_MODEL to a cheap model)
        risk_mgr: RiskManager instance
        ohlcv: {asset: [candle_dict, ...]} — pre-loaded historical data
        assets: list of asset names matching ohlcv keys
        initial_balance: starting paper balance in USD
        candles_per_step: how many candles to advance per loop iteration
        diary_path: path for backtest diary output
    """
    sim = SimulatedAPI(ohlcv=ohlcv, initial_balance=initial_balance)

    # Patch run_loop to advance the sim cursor on each sleep
    original_sleep = asyncio.sleep

    async def _patched_sleep(seconds):
        for _ in range(candles_per_step):
            sim.advance()
        if sim.is_done():
            raise _BacktestDone()
        await original_sleep(0)  # yield control without blocking

    asyncio.sleep = _patched_sleep  # type: ignore[assignment]

    # Clear previous diary
    try:
        os.remove(diary_path)
    except FileNotFoundError:
        pass

    from src.notifications.emailer import Emailer
    emailer = Emailer()  # no-op in tests (no email config)

    try:
        await run_loop(
            hyperliquid=sim,
            agent=agent,
            risk_mgr=risk_mgr,
            emailer=emailer,
            assets=assets,
            interval_seconds=0,
            start_time=datetime.now(timezone.utc),
            diary_path=diary_path,
        )
    except _BacktestDone:
        pass
    finally:
        asyncio.sleep = original_sleep  # type: ignore[assignment]

    final_state = await sim.get_user_state()
    final_balance = float(final_state.get("total_value", initial_balance))

    report = _compute_report(initial_balance, final_balance, sim._fills)
    logging.info(
        "Backtest complete — return: %.2f%%, trades: %d, Sharpe: %.3f",
        report["total_return_pct"], report["total_trades"], report["sharpe"],
    )
    return report
