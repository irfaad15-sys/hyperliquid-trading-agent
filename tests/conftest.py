"""Global test configuration — sets required env vars before any module import."""

import os

# Must be set before src.config_loader is imported (it runs at import time)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-placeholder")
os.environ.setdefault("HYPERLIQUID_PRIVATE_KEY", "0xtest")
os.environ.setdefault("HYPERLIQUID_VAULT_ADDRESS", "0xtest")
