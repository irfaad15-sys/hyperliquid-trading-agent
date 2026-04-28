"""Main trading loop — orchestrates per-cycle data fetch, LLM call, and execution."""

import asyncio
import json
import logging
import math
import os
import traceback
from collections import OrderedDict, deque
from datetime import datetime, timezone

from src.indicators.local_indicators import compute_all, last_n, latest
from src.loop.dashboard import build_dashboard
from src.loop.executor import execute_trades
from src.loop.reconciler import fetch_fills, reconcile_active_trades
from src.loop.state_builder import build_account_state
from src.utils.prompt_utils import json_default, round_or_none, round_series


def calculate_sharpe(returns: list) -> float:
    if not returns:
        return 0
    vals = [r.get('pnl', 0) if 'pnl' in r else 0 for r in returns]
    if not vals:
        return 0
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    std = math.sqrt(var) if var > 0 else 0
    return mean / std if std > 0 else 0


def _is_failed_outputs(outs) -> bool:
    if not isinstance(outs, dict):
        return True
    decisions = outs.get("trade_decisions")
    if not isinstance(decisions, list) or not decisions:
        return True
    try:
        return all(
            isinstance(o, dict)
            and (o.get('action') == 'hold')
            and ('parse error' in (o.get('rationale', '').lower()))
            for o in decisions
        )
    except Exception:
        return True


async def run_loop(
    hyperliquid,
    agent,
    risk_mgr,
    emailer,
    assets: list,
    interval_seconds: int,
    start_time: datetime,
    diary_path: str,
) -> None:
    """Run the trading loop indefinitely until cancelled."""
    invocation_count = 0
    trade_log: list = []
    active_trades: list = []
    initial_account_value: float | None = None
    total_return_pct: float = 0.0
    price_history: dict = {}

    await hyperliquid.get_meta_and_ctxs()
    hip3_dexes = set()
    for a in assets:
        if ":" in a:
            hip3_dexes.add(a.split(":")[0])
    for dex in hip3_dexes:
        await hyperliquid.get_meta_and_ctxs(dex=dex)
        logging.info(f"Loaded HIP-3 meta for dex: {dex}")

    async def _fetch_asset_data(asset):
        current_price, oi, funding, candles_5m, candles_4h = await asyncio.gather(
            hyperliquid.get_current_price(asset),
            hyperliquid.get_open_interest(asset),
            hyperliquid.get_funding_rate(asset),
            hyperliquid.get_candles(asset, "5m", 100),
            hyperliquid.get_candles(asset, "4h", 100),
        )
        return asset, current_price, oi, funding, candles_5m, candles_4h

    while True:
        invocation_count += 1
        minutes_since_start = (datetime.now(timezone.utc) - start_time).total_seconds() / 60

        state = await hyperliquid.get_user_state()
        emailer.maybe_send_digest(
            balance=float(state.get('balance', 0)),
            daily_return_pct=total_return_pct if invocation_count > 1 else 0.0,
            open_positions=len([p for p in state.get('positions', []) if abs(float(p.get('szi') or 0)) > 0]),
        )

        balance, total_value, positions = await build_account_state(state, hyperliquid)
        account_value = total_value
        if initial_account_value is None:
            initial_account_value = account_value
        total_return_pct = ((account_value - initial_account_value) / initial_account_value * 100.0) if initial_account_value else 0.0
        sharpe = calculate_sharpe(trade_log)

        # Force-close positions exceeding max loss
        try:
            positions_to_close = risk_mgr.check_losing_positions(state.get('positions', []))
            for ptc in positions_to_close:
                coin = ptc["coin"]
                size = ptc["size"]
                is_long = ptc["is_long"]
                logging.info(f"RISK FORCE-CLOSE: {coin} at {ptc['loss_pct']}% loss (PnL: ${ptc['pnl']})")
                emailer.send_alert(
                    f"Force-close: {coin} -{ptc['loss_pct']}%",
                    f"Asset: {coin}\nLoss: {ptc['loss_pct']}%\nPnL: ${ptc['pnl']}\n"
                    f"Balance: ${round_or_none(state.get('balance', 0), 2)}\n"
                    f"Time: {datetime.now(timezone.utc).isoformat()}"
                )
                try:
                    if is_long:
                        await hyperliquid.place_sell_order(coin, size)
                    else:
                        await hyperliquid.place_buy_order(coin, size)
                    await hyperliquid.cancel_all_orders(coin)
                    for tr in active_trades[:]:
                        if tr.get('asset') == coin:
                            active_trades.remove(tr)
                    with open(diary_path, "a") as f:
                        f.write(json.dumps({
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "asset": coin,
                            "action": "risk_force_close",
                            "loss_pct": ptc["loss_pct"],
                            "pnl": ptc["pnl"],
                        }) + "\n")
                except Exception as fc_err:
                    logging.info(f"Force-close error for {coin}: {fc_err}")
        except Exception as risk_err:
            logging.info(f"Risk check error: {risk_err}")

        recent_diary: list = []
        try:
            with open(diary_path, "r") as f:
                lines = f.readlines()
            for line in lines[-10:]:
                recent_diary.append(json.loads(line))
        except Exception:
            pass

        open_orders_struct: list = []
        try:
            open_orders = await hyperliquid.get_open_orders()
            for o in open_orders[:50]:
                open_orders_struct.append({
                    "coin": o.get('coin'),
                    "oid": o.get('oid'),
                    "is_buy": o.get('isBuy'),
                    "size": round_or_none(o.get('sz'), 6),
                    "price": round_or_none(o.get('px'), 2),
                    "trigger_price": round_or_none(o.get('triggerPx'), 2),
                    "order_type": o.get('orderType'),
                })
        except Exception:
            pass

        reconcile_active_trades(active_trades, state, open_orders_struct, diary_path)
        recent_fills = await fetch_fills(hyperliquid)

        dashboard = build_dashboard(
            total_return_pct=total_return_pct,
            balance=balance,
            account_value=account_value,
            sharpe=sharpe,
            positions=positions,
            active_trades=active_trades,
            open_orders=open_orders_struct,
            recent_diary=recent_diary,
            recent_fills=recent_fills,
        )

        raw_results = await asyncio.gather(
            *[_fetch_asset_data(a) for a in assets],
            return_exceptions=True,
        )
        market_sections: list = []
        asset_prices: dict = {}
        for result in raw_results:
            if isinstance(result, Exception):
                logging.info(f"Data gather error: {result}")
                continue
            try:
                asset, current_price, oi, funding, candles_5m, candles_4h = result
                asset_prices[asset] = current_price
                if asset not in price_history:
                    price_history[asset] = deque(maxlen=60)
                price_history[asset].append({"t": datetime.now(timezone.utc).isoformat(), "mid": round_or_none(current_price, 2)})
                intra = compute_all(candles_5m)
                lt = compute_all(candles_4h)
                recent_mids = [entry["mid"] for entry in list(price_history.get(asset, []))[-10:]]
                funding_annualized = round(funding * 24 * 365 * 100, 2) if funding else None
                market_sections.append({
                    "asset": asset,
                    "current_price": round_or_none(current_price, 2),
                    "intraday": {
                        "ema20": round_or_none(latest(intra.get("ema20", [])), 2),
                        "macd": round_or_none(latest(intra.get("macd", [])), 2),
                        "rsi7": round_or_none(latest(intra.get("rsi7", [])), 2),
                        "rsi14": round_or_none(latest(intra.get("rsi14", [])), 2),
                        "series": {
                            "ema20": round_series(last_n(intra.get("ema20", []), 10), 2),
                            "macd": round_series(last_n(intra.get("macd", []), 10), 2),
                            "rsi7": round_series(last_n(intra.get("rsi7", []), 10), 2),
                            "rsi14": round_series(last_n(intra.get("rsi14", []), 10), 2),
                        },
                    },
                    "long_term": {
                        "ema20": round_or_none(latest(lt.get("ema20", [])), 2),
                        "ema50": round_or_none(latest(lt.get("ema50", [])), 2),
                        "atr3": round_or_none(latest(lt.get("atr3", [])), 2),
                        "atr14": round_or_none(latest(lt.get("atr14", [])), 2),
                        "macd_series": round_series(last_n(lt.get("macd", []), 10), 2),
                        "rsi_series": round_series(last_n(lt.get("rsi14", []), 10), 2),
                    },
                    "open_interest": round_or_none(oi, 2),
                    "funding_rate": round_or_none(funding, 8),
                    "funding_annualized_pct": funding_annualized,
                    "recent_mid_prices": recent_mids,
                })
            except Exception as e:
                logging.info(f"Data process error {result[0] if result else '?'}: {e}")
                continue

        context_payload = OrderedDict([
            ("invocation", {
                "minutes_since_start": round(minutes_since_start, 2),
                "current_time": datetime.now(timezone.utc).isoformat(),
                "invocation_count": invocation_count,
            }),
            ("account", dashboard),
            ("risk_limits", risk_mgr.get_risk_summary()),
            ("market_data", market_sections),
            ("instructions", {
                "assets": assets,
                "requirement": "Decide actions for all assets and return a strict JSON object matching the schema.",
            }),
        ])
        context = json.dumps(context_payload, sort_keys=True, default=json_default)
        logging.info(f"Combined prompt length: {len(context)} chars for {len(assets)} assets")
        if os.getenv("LOG_FULL_PROMPT", "false").lower() == "true":
            with open("prompts.log", "a") as f:
                f.write(f"\n\n--- {datetime.now()} - ALL ASSETS ---\n"
                        f"{json.dumps(context_payload, indent=2, sort_keys=True, default=json_default)}\n")

        try:
            outputs = agent.decide_trade(assets, context)
            if not isinstance(outputs, dict):
                logging.info(f"Invalid output format (expected dict): {outputs}")
                outputs = {}
        except Exception as e:
            logging.info(f"Agent error: {e}")
            logging.info(f"Traceback: {traceback.format_exc()}")
            outputs = {}

        if _is_failed_outputs(outputs):
            logging.info("Retrying LLM once due to invalid/parse-error output")
            context_retry_payload = OrderedDict([
                ("retry_instruction", "Return ONLY the JSON array per schema with no prose."),
                ("original_context", context_payload),
            ])
            context_retry = json.dumps(context_retry_payload, sort_keys=True, default=json_default)
            try:
                outputs = agent.decide_trade(assets, context_retry)
                if not isinstance(outputs, dict):
                    logging.info(f"Retry invalid format: {outputs}")
                    outputs = {}
            except Exception as e:
                logging.info(f"Retry agent error: {e}")
                logging.info(f"Retry traceback: {traceback.format_exc()}")
                outputs = {}

        reasoning_text = outputs.get("reasoning", "") if isinstance(outputs, dict) else ""
        if reasoning_text:
            logging.info(f"LLM reasoning summary: {reasoning_text}")

        cycle_decisions = []
        for d in outputs.get("trade_decisions", []) if isinstance(outputs, dict) else []:
            cycle_decisions.append({
                "asset": d.get("asset"),
                "action": d.get("action", "hold"),
                "allocation_usd": d.get("allocation_usd", 0),
                "rationale": d.get("rationale", ""),
            })
        cycle_log = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycle": invocation_count,
            "reasoning": reasoning_text[:2000] if reasoning_text else "",
            "decisions": cycle_decisions,
            "account_value": round_or_none(account_value, 2),
            "balance": round_or_none(state.get('balance', 0), 2),
            "positions_count": len([p for p in state.get('positions', []) if abs(float(p.get('szi') or 0)) > 0]),
        }
        try:
            with open("decisions.jsonl", "a") as f:
                f.write(json.dumps(cycle_log) + "\n")
        except Exception:
            pass

        await execute_trades(
            outputs=outputs,
            assets=assets,
            asset_prices=asset_prices,
            state=state,
            risk_mgr=risk_mgr,
            hyperliquid=hyperliquid,
            active_trades=active_trades,
            emailer=emailer,
            diary_path=diary_path,
            initial_account_value=initial_account_value or 0,
            trade_log=trade_log,
        )

        await asyncio.sleep(interval_seconds)
