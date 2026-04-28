"""Simulated Hyperliquid API for backtesting — replays historical OHLCV data."""

from collections import defaultdict


class SimulatedAPI:
    """Drop-in replacement for HyperliquidAPI during backtesting.

    Feeds pre-loaded OHLCV candles to the agent loop so no live API calls
    are made. Tracks simulated orders and balance.
    """

    is_simulation = True  # signals executor.py to skip fill-confirmation sleep

    def __init__(self, ohlcv: dict[str, list[dict]], initial_balance: float = 10_000.0):
        """
        Args:
            ohlcv: {asset: [{"t": ms_timestamp, "o": open, "h": high, "l": low,
                              "c": close, "v": volume}, ...]}
            initial_balance: starting paper-money balance in USD
        """
        self._ohlcv = ohlcv
        self._cursor: dict[str, int] = {asset: 0 for asset in ohlcv}
        self._balance = initial_balance
        self._positions: dict[str, dict] = {}  # asset → {szi, entryPx, pnl}
        self._fills: list[dict] = []
        self._tick = 0  # current candle index (shared across assets)

    # ------------------------------------------------------------------
    # Cursor control — called by backtest runner to advance time
    # ------------------------------------------------------------------

    def advance(self):
        """Move to the next candle across all assets."""
        self._tick += 1
        for asset in self._cursor:
            if self._cursor[asset] < len(self._ohlcv[asset]) - 1:
                self._cursor[asset] += 1

    def is_done(self) -> bool:
        """Return True when all assets have exhausted their candle history."""
        return all(
            self._cursor[a] >= len(self._ohlcv[a]) - 1
            for a in self._ohlcv
        )

    def current_candle(self, asset: str) -> dict | None:
        idx = self._cursor.get(asset, 0)
        candles = self._ohlcv.get(asset, [])
        return candles[idx] if idx < len(candles) else None

    # ------------------------------------------------------------------
    # HyperliquidAPI interface — async wrappers over in-memory data
    # ------------------------------------------------------------------

    async def get_meta_and_ctxs(self, dex: str | None = None):
        return {}

    async def get_user_state(self) -> dict:
        total_pnl = sum(p.get("pnl", 0) for p in self._positions.values())
        positions_list = [
            {
                "coin": asset,
                "szi": str(pos["szi"]),
                "entryPx": str(pos["entryPx"]),
                "pnl": pos["pnl"],
                "leverage": {"type": "cross", "value": 1},
            }
            for asset, pos in self._positions.items()
            if pos["szi"] != 0
        ]
        return {
            "balance": round(self._balance, 4),
            "total_value": round(self._balance + total_pnl, 4),
            "positions": positions_list,
        }

    async def get_current_price(self, asset: str) -> float | None:
        candle = self.current_candle(asset)
        return float(candle["c"]) if candle else None

    async def get_open_interest(self, asset: str) -> float | None:
        return None

    async def get_funding_rate(self, asset: str) -> float | None:
        return None

    async def get_candles(self, asset: str, interval: str, limit: int) -> list[dict]:
        idx = self._cursor.get(asset, 0)
        candles = self._ohlcv.get(asset, [])
        start = max(0, idx - limit + 1)
        return candles[start : idx + 1]

    async def get_open_orders(self) -> list:
        return []

    async def get_recent_fills(self, limit: int = 50) -> list:
        return self._fills[-limit:]

    async def place_buy_order(self, asset: str, amount: float) -> dict:
        return self._fill_order(asset, amount, is_buy=True)

    async def place_sell_order(self, asset: str, amount: float) -> dict:
        return self._fill_order(asset, amount, is_buy=False)

    async def place_limit_buy(self, asset: str, amount: float, price: float) -> dict:
        return self._fill_order(asset, amount, is_buy=True)

    async def place_limit_sell(self, asset: str, amount: float, price: float) -> dict:
        return self._fill_order(asset, amount, is_buy=False)

    async def place_take_profit(self, asset: str, is_buy: bool, amount: float, price: float) -> dict:
        return {}

    async def place_stop_loss(self, asset: str, is_buy: bool, amount: float, price: float) -> dict:
        return {}

    async def cancel_all_orders(self, asset: str) -> dict:
        return {}

    def extract_oids(self, order_result: dict) -> list:
        return []

    # ------------------------------------------------------------------
    # Internal order fill simulation
    # ------------------------------------------------------------------

    def _fill_order(self, asset: str, amount: float, is_buy: bool) -> dict:
        candle = self.current_candle(asset)
        price = float(candle["c"]) if candle else 0.0
        cost = amount * price

        if is_buy:
            self._balance -= cost
            existing = self._positions.get(asset, {"szi": 0, "entryPx": price, "pnl": 0})
            new_szi = existing["szi"] + amount
            self._positions[asset] = {"szi": new_szi, "entryPx": price, "pnl": 0}
        else:
            pos = self._positions.get(asset)
            if pos and pos["szi"] > 0:
                self._balance += cost  # sale proceeds already include profit
                new_szi = max(0.0, pos["szi"] - amount)
                self._positions[asset] = {**pos, "szi": new_szi, "pnl": 0 if new_szi == 0 else pos["pnl"]}
            else:
                self._balance += cost

        fill = {
            "coin": asset,
            "isBuy": is_buy,
            "sz": str(round(amount, 6)),
            "px": str(round(price, 2)),
            "time": str(self._tick * 1000),
        }
        self._fills.append(fill)
        return {"status": "ok", "price": price, "amount": amount}
