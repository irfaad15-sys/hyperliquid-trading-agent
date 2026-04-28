"""Fetch and normalize account state from the raw Hyperliquid API response."""

import asyncio
import logging

from src.utils.prompt_utils import round_or_none


async def build_account_state(
    raw_state: dict,
    hyperliquid,
) -> tuple[float, float, list]:
    """Return (balance, total_value, positions).

    positions: list of enriched dicts with current_price added.
    total_value: portfolio value including unrealized PnL.
    """
    balance = raw_state.get('balance', 0.0)
    if balance == 0.0:
        logging.warning("Account balance is 0 — API response may be incomplete")
    total_value = raw_state.get('total_value') or balance + sum(
        p.get('pnl', 0) for p in raw_state.get('positions', [])
    )

    async def _price(coin):
        return await hyperliquid.get_current_price(coin) if coin else None

    raw_positions = raw_state.get('positions', [])
    prices = await asyncio.gather(
        *[_price(p.get('coin')) for p in raw_positions],
        return_exceptions=True,
    )

    positions = []
    for pos, current_px in zip(raw_positions, prices):
        if isinstance(current_px, Exception):
            current_px = None
        positions.append({
            "symbol": pos.get('coin'),
            "quantity": round_or_none(pos.get('szi'), 6),
            "entry_price": round_or_none(pos.get('entryPx'), 2),
            "current_price": round_or_none(current_px, 2),
            "liquidation_price": round_or_none(pos.get('liquidationPx') or pos.get('liqPx'), 2),
            "unrealized_pnl": round_or_none(pos.get('pnl'), 4),
            "leverage": pos.get('leverage'),
        })

    return balance, total_value, positions
