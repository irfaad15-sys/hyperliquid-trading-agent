"""Entry-point: parse args, wire dependencies, run the HTTP API and trading loop."""

import sys
import pathlib
sys.path.append(str(pathlib.Path(__file__).parent.parent))

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from aiohttp import web
from dotenv import load_dotenv

from src.agent.decision_maker import TradingAgent
from src.config_loader import CONFIG
from src.loop.runner import run_loop
from src.notifications.emailer import Emailer
from src.risk_manager import RiskManager
from src.trading.hyperliquid_api import HyperliquidAPI

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

DIARY_PATH = "diary.jsonl"


def clear_terminal():
    os.system('cls' if os.name == 'nt' else 'clear')


def get_interval_seconds(interval_str: str) -> int:
    if interval_str.endswith('m'):
        return int(interval_str[:-1]) * 60
    elif interval_str.endswith('h'):
        return int(interval_str[:-1]) * 3600
    elif interval_str.endswith('d'):
        return int(interval_str[:-1]) * 86400
    raise ValueError(f"Unsupported interval: {interval_str}")


async def handle_diary(request):
    try:
        raw = request.query.get('raw')
        download = request.query.get('download')
        if raw or download:
            if not os.path.exists(DIARY_PATH):
                return web.Response(text="", content_type="text/plain")
            with open(DIARY_PATH, "r") as f:
                data = f.read()
            headers = {}
            if download:
                headers["Content-Disposition"] = "attachment; filename=diary.jsonl"
            return web.Response(text=data, content_type="text/plain", headers=headers)
        limit = int(request.query.get('limit', '200'))
        with open(DIARY_PATH, "r") as f:
            lines = f.readlines()
        start = max(0, len(lines) - limit)
        entries = [json.loads(l) for l in lines[start:]]
        return web.json_response({"entries": entries})
    except FileNotFoundError:
        return web.json_response({"entries": []})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_logs(request):
    try:
        path = request.query.get('path', 'llm_requests.log')
        download = request.query.get('download')
        limit_param = request.query.get('limit')
        if not os.path.exists(path):
            return web.Response(text="", content_type="text/plain")
        with open(path, "r") as f:
            data = f.read()
        if download or (limit_param and (limit_param.lower() == 'all' or limit_param == '-1')):
            headers = {}
            if download:
                headers["Content-Disposition"] = f"attachment; filename={os.path.basename(path)}"
            return web.Response(text=data, content_type="text/plain", headers=headers)
        limit = int(limit_param) if limit_param else 2000
        return web.Response(text=data[-limit:], content_type="text/plain")
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


def main():
    clear_terminal()
    parser = argparse.ArgumentParser(description="LLM-based Trading Agent on Hyperliquid")
    parser.add_argument("--assets", type=str, nargs="+", required=False)
    parser.add_argument("--interval", type=str, required=False)
    args = parser.parse_args()

    assets_env = CONFIG.get("assets")
    interval_env = CONFIG.get("interval")
    if (not args.assets or len(args.assets) == 0) and assets_env:
        if "," in assets_env:
            args.assets = [a.strip() for a in assets_env.split(",") if a.strip()]
        else:
            args.assets = [a.strip() for a in assets_env.split(" ") if a.strip()]
    if not args.interval and interval_env:
        args.interval = interval_env

    if not args.assets or not args.interval:
        parser.error("Please provide --assets and --interval, or set ASSETS and INTERVAL in .env")

    hyperliquid = HyperliquidAPI()
    agent = TradingAgent(hyperliquid=hyperliquid)
    risk_mgr = RiskManager()
    emailer = Emailer()
    interval_seconds = get_interval_seconds(args.interval)

    print(f"Starting trading agent for assets: {args.assets} at interval: {args.interval}")

    async def main_async():
        app = web.Application()
        app.router.add_get('/diary', handle_diary)
        app.router.add_get('/logs', handle_logs)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, CONFIG.get("api_host"), int(CONFIG.get("api_port")))
        await site.start()
        await run_loop(
            hyperliquid=hyperliquid,
            agent=agent,
            risk_mgr=risk_mgr,
            emailer=emailer,
            assets=args.assets,
            interval_seconds=interval_seconds,
            start_time=datetime.now(timezone.utc),
            diary_path=DIARY_PATH,
        )

    asyncio.run(main_async())


if __name__ == "__main__":
    main()
