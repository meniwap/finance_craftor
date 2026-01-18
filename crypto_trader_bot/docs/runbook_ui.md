## Runbook: Local UI (FastAPI)

### What this UI is
Local control panel for:
- Creating sessions (without editing YAML)
- Starting/stopping/pausing sessions
- Viewing balances/positions/open orders/fills
- Viewing decision logs (why we entered / why we blocked)

### Start the UI

From `crypto_trader_bot/`:

```bash
. .venv/bin/activate
python -m uvicorn src.app.ui_server:app --host 127.0.0.1 --port 8000
```

Open: `http://127.0.0.1:8000/`

### Security (recommended even locally)

Set a UI token and use it in the UI settings tab.

```bash
export UI_TOKEN="change-me"
```

The UI will send it as `X-UI-TOKEN`.

### Permission modes

```bash
# allow everything (default)
export UI_MODE="live"

# block live mode starts (paper/backtest only)
export UI_MODE="paper_only"

# block all write operations (read-only dashboard)
export UI_MODE="read_only"
```

### Live confirmation gate

To require an explicit confirmation checkbox before any live action:

```bash
export UI_REQUIRE_LIVE_CONFIRM="true"
```

Then you must tick “אני מאשר Live” in the UI settings before Start/Manual Trade.

### Troubleshooting

- **401 missing/invalid UI token**: set `UI_TOKEN` (server) and fill it in the UI settings.
- **403 paper-only mode**: set `UI_MODE=live` if you really want live.
- **No trades**: check the “לוגים” tab → `Decision Log` to see which rule blocked entries.

