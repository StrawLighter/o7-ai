"""Root-level conftest: mock external SDK modules for testing.

This runs before any warpath module is imported, ensuring that
driftpy, solana, and solders imports don't fail in tests.
"""

import sys
from unittest.mock import MagicMock

# Mock external SDK modules that aren't installed in test env
MOCK_MODULES = [
    "solana",
    "solana.rpc",
    "solana.rpc.async_api",
    "solders",
    "solders.keypair",
    "driftpy",
    "driftpy.drift_client",
    "driftpy.drift_user",
    "driftpy.types",
    "driftpy.config",
    "driftpy.constants",
    "driftpy.constants.numeric_constants",
    "driftpy.accounts",
    "telegram",
    "telegram.ext",
]

for mod_name in MOCK_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
