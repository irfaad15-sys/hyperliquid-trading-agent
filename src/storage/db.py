"""SQLite persistence for active_trades — survives crashes and restarts."""

import json
import logging
from datetime import datetime, timezone

import aiosqlite


async def init_db(db_path: str) -> None:
    """Create tables if they don't exist."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS active_trades (
                asset TEXT PRIMARY KEY,
                data  TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.commit()


async def load_active_trades(db_path: str) -> list[dict]:
    """Return all persisted active trades as a list of dicts."""
    try:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT data FROM active_trades") as cur:
                rows = await cur.fetchall()
        return [json.loads(row[0]) for row in rows]
    except Exception as e:
        logging.warning("Could not load active_trades from DB: %s", e)
        return []


async def save_all_active_trades(db_path: str, active_trades: list[dict]) -> None:
    """Overwrite the active_trades table with the current in-memory list."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("DELETE FROM active_trades")
            for trade in active_trades:
                asset = trade.get("asset", "")
                await db.execute(
                    "INSERT OR REPLACE INTO active_trades (asset, data, updated_at) VALUES (?, ?, ?)",
                    (asset, json.dumps(trade), now),
                )
            await db.commit()
    except Exception as e:
        logging.warning("Could not persist active_trades to DB: %s", e)
