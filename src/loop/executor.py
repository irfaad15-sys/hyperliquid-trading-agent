"""Execute buy/sell/hold decisions from the LLM output against Hyperliquid."""

import asyncio
import json
import logging
import time
import traceback
from datetime import datetime, timezone

from src.utils.prompt_utils import round_or_none


async def execute_trades(
    outputs: dict,
    assets: list,
    asset_prices: dict,
    state: dict,
    risk_mgr,
    hyperliquid,
    active_trades: list,
    emailer,
    diary_path: str,
    initial_account_value: float,
    trade_log: list,
) -> None:
    """Execute all trade decisions from the LLM output.

    Mutates active_trades and trade_log in-place.
    """
    for output in outputs.get("trade_decisions", []) if isinstance(outputs, dict) else []:
        try:
            asset = output.get("asset")
            if not asset or asset not in assets:
                continue
            action = output.get("action", "hold")
            current_price = asset_prices.get(asset, 0)
            rationale = output.get("rationale", "")
            if rationale:
                logging.info(f"Decision rationale for {asset}: {rationale}")

            if action in ("buy", "sell"):
                is_buy = action == "buy"
                alloc_usd = float(output.get("allocation_usd", 0.0))
                if alloc_usd <= 0:
                    logging.info(f"Holding {asset}: zero/negative allocation")
                    continue

                output["current_price"] = current_price
                allowed, reason, output = risk_mgr.validate_trade(
                    output, state, initial_account_value or 0
                )
                if not allowed:
                    logging.info(f"RISK BLOCKED {asset}: {reason}")
                    if "circuit breaker" in reason.lower():
                        emailer.send_alert(
                            "Circuit breaker active — trading halted",
                            f"Reason: {reason}\n"
                            f"Balance: ${round_or_none(state.get('balance', 0), 2)}\n"
                            f"Time: {datetime.now(timezone.utc).isoformat()}"
                        )
                    with open(diary_path, "a") as f:
                        f.write(json.dumps({
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "asset": asset,
                            "action": "risk_blocked",
                            "reason": reason,
                            "original_alloc_usd": alloc_usd,
                        }) + "\n")
                    continue

                alloc_usd = float(output.get("allocation_usd", alloc_usd))
                amount = alloc_usd / current_price

                order_type = output.get("order_type", "market")
                limit_price = output.get("limit_price")

                if order_type == "limit" and limit_price:
                    limit_price = float(limit_price)
                    if is_buy:
                        order = await hyperliquid.place_limit_buy(asset, amount, limit_price)
                    else:
                        order = await hyperliquid.place_limit_sell(asset, amount, limit_price)
                    logging.info(f"LIMIT {action.upper()} {asset} amount {amount:.4f} at limit ${limit_price}")
                else:
                    if is_buy:
                        order = await hyperliquid.place_buy_order(asset, amount)
                    else:
                        order = await hyperliquid.place_sell_order(asset, amount)

                # Confirm fill within 30-second window
                await asyncio.sleep(1)
                fills_check = await hyperliquid.get_recent_fills(limit=10)
                cutoff_ms = (time.time() - 30) * 1000
                filled = False
                for fc in reversed(fills_check):
                    try:
                        fill_time = int(fc.get('time') or fc.get('timestamp') or 0)
                        coin_match = (fc.get('coin') == asset or fc.get('asset') == asset)
                        if coin_match and fill_time > cutoff_ms:
                            filled = True
                            break
                    except Exception:
                        continue

                trade_log.append({
                    "type": action,
                    "price": current_price,
                    "amount": amount,
                    "exit_plan": output.get("exit_plan", ""),
                    "filled": filled,
                })

                tp_oid = None
                sl_oid = None
                if output.get("tp_price"):
                    tp_order = await hyperliquid.place_take_profit(asset, is_buy, amount, output["tp_price"])
                    tp_oids = hyperliquid.extract_oids(tp_order)
                    tp_oid = tp_oids[0] if tp_oids else None
                    logging.info(f"TP placed {asset} at {output['tp_price']}")
                if output.get("sl_price"):
                    sl_order = await hyperliquid.place_stop_loss(asset, is_buy, amount, output["sl_price"])
                    sl_oids = hyperliquid.extract_oids(sl_order)
                    sl_oid = sl_oids[0] if sl_oids else None
                    logging.info(f"SL placed {asset} at {output['sl_price']}")

                for existing in active_trades[:]:
                    if existing.get('asset') == asset:
                        try:
                            active_trades.remove(existing)
                        except ValueError:
                            pass
                active_trades.append({
                    "asset": asset,
                    "is_long": is_buy,
                    "amount": amount,
                    "entry_price": current_price,
                    "tp_oid": tp_oid,
                    "sl_oid": sl_oid,
                    "exit_plan": output.get("exit_plan", ""),
                    "opened_at": datetime.now().isoformat(),
                })
                logging.info(f"{action.upper()} {asset} amount {amount:.4f} at ~{current_price}")
                emailer.record_trade()
                if rationale:
                    logging.info(f"Post-trade rationale for {asset}: {rationale}")

                with open(diary_path, "a") as f:
                    f.write(json.dumps({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "asset": asset,
                        "action": action,
                        "order_type": order_type,
                        "limit_price": limit_price,
                        "allocation_usd": alloc_usd,
                        "amount": amount,
                        "entry_price": current_price,
                        "tp_price": output.get("tp_price"),
                        "tp_oid": tp_oid,
                        "sl_price": output.get("sl_price"),
                        "sl_oid": sl_oid,
                        "exit_plan": output.get("exit_plan", ""),
                        "rationale": output.get("rationale", ""),
                        "order_result": str(order),
                        "opened_at": datetime.now(timezone.utc).isoformat(),
                        "filled": filled,
                    }) + "\n")

            else:
                logging.info(f"Hold {asset}: {output.get('rationale', '')}")
                with open(diary_path, "a") as f:
                    f.write(json.dumps({
                        "timestamp": datetime.now().isoformat(),
                        "asset": asset,
                        "action": "hold",
                        "rationale": output.get("rationale", ""),
                    }) + "\n")

        except Exception as e:
            logging.info(f"Execution error {asset}: {e}")
            logging.info(f"Traceback: {traceback.format_exc()}")
