from __future__ import annotations

import sys
from pathlib import Path


# Ensure `import src.*` works when running tests without installing the package.
# The repository layout is: crypto_trader_bot/src/ (package root contains `src/` package)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

