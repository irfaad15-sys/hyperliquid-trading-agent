"""Load recent trade outcomes from diary for LLM feedback (C3 post-trade learning)."""

import json
import logging
import os

_LEARNING_ACTIONS = {"buy", "sell", "risk_force_close"}
_DEFAULT_WINDOW = 5


def load_recent_outcomes(diary_path: str) -> list:
    """Return the last N closed trade outcomes from the diary for LLM context.

    N is controlled by LEARNING_WINDOW env var (default 5, 0 to disable).
    Returns [] if diary is missing or LEARNING_WINDOW=0.
    Entries are returned in chronological order (oldest first).
    """
    window = int(os.getenv("LEARNING_WINDOW", str(_DEFAULT_WINDOW)))
    if window <= 0:
        return []
    try:
        with open(diary_path, "r") as f:
            lines = f.readlines()
        outcomes = []
        for line in reversed(lines):
            try:
                entry = json.loads(line)
                if entry.get("action") in _LEARNING_ACTIONS:
                    outcomes.append({
                        "timestamp": entry.get("timestamp"),
                        "asset": entry.get("asset"),
                        "action": entry.get("action"),
                        "entry_price": entry.get("entry_price"),
                        "allocation_usd": entry.get("allocation_usd"),
                        "filled": entry.get("filled"),
                        "pnl": entry.get("pnl"),
                        "loss_pct": entry.get("loss_pct"),
                        "rationale": entry.get("rationale"),
                    })
                    if len(outcomes) >= window:
                        break
            except Exception:
                continue
        return list(reversed(outcomes))
    except FileNotFoundError:
        return []
    except Exception:
        logging.debug("Could not load recent outcomes from diary")
        return []
