"""Reconcile active_trades with live exchange state; fetch and format recent fills."""

import json
import logging
from datetime import datetime, timezone

from src.utils.prompt_utils import round_or_none


def reconcile_active_trades(
    active_trades: list,
    state: dict,
    open_orders: list,
    diary_path: str,
) -> None:
    """Remove stale active_trades entries with no live position or open order.

    Mutates active_trades in-place.
    """
    try:
        assets_with_positions = set()
        for pos in state.get('positions', []):
            try:
                if abs(float(pos.get('szi') or 0)) > 0:
                    assets_with_positions.add(pos.get('coin'))
            except Exception:
                continue
        assets_with_orders = {o.get('coin') for o in (open_orders or []) if o.get('coin')}
        for tr in active_trades[:]:
            asset = tr.get('asset')
            if asset not in assets_with_positions and asset not in assets_with_orders:
                logging.info(f"Reconciling stale active trade for {asset} (no position, no orders)")
                active_trades.remove(tr)
                with open(diary_path, "a") as f:
                    f.write(json.dumps({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "asset": asset,
                        "action": "reconcile_close",
                        "reason": "no_position_no_orders",
                        "opened_at": tr.get('opened_at'),
                    }) + "\n")
    except Exception:
        pass


async def fetch_fills(hyperliquid) -> list:
    """Return up to 20 recent fills formatted for prompt context."""
    result = []
    try:
        fills = await hyperliquid.get_recent_fills(limit=50)
        for f_entry in fills[-20:]:
            try:
                t_raw = f_entry.get('time') or f_entry.get('timestamp')
                timestamp = None
                if t_raw is not None:
                    try:
                        t_int = int(t_raw)
                        if t_int > 1e12:
                            timestamp = datetime.fromtimestamp(t_int / 1000, tz=timezone.utc).isoformat()
                        else:
                            timestamp = datetime.fromtimestamp(t_int, tz=timezone.utc).isoformat()
                    except Exception:
                        timestamp = str(t_raw)
                result.append({
                    "timestamp": timestamp,
                    "coin": f_entry.get('coin') or f_entry.get('asset'),
                    "is_buy": f_entry.get('isBuy'),
                    "size": round_or_none(f_entry.get('sz') or f_entry.get('size'), 6),
                    "price": round_or_none(f_entry.get('px') or f_entry.get('price'), 2),
                })
            except Exception:
                continue
    except Exception:
        pass
    return result
