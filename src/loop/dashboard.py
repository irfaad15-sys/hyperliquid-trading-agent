"""Assemble the per-cycle dashboard dict for the API endpoint and LLM prompt."""

from src.utils.prompt_utils import round_or_none


def build_dashboard(
    total_return_pct: float,
    balance: float,
    account_value: float,
    sharpe: float,
    positions: list,
    active_trades: list,
    open_orders: list,
    recent_diary: list,
    recent_fills: list,
) -> dict:
    return {
        "total_return_pct": round(total_return_pct, 2),
        "balance": round_or_none(balance, 2),
        "account_value": round_or_none(account_value, 2),
        "sharpe_ratio": round_or_none(sharpe, 3),
        "positions": positions,
        "active_trades": [
            {
                "asset": tr.get('asset'),
                "is_long": tr.get('is_long'),
                "amount": round_or_none(tr.get('amount'), 6),
                "entry_price": round_or_none(tr.get('entry_price'), 2),
                "tp_oid": tr.get('tp_oid'),
                "sl_oid": tr.get('sl_oid'),
                "exit_plan": tr.get('exit_plan'),
                "opened_at": tr.get('opened_at'),
            }
            for tr in active_trades
        ],
        "open_orders": open_orders,
        "recent_diary": recent_diary,
        "recent_fills": recent_fills,
    }
