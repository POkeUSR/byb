# Bybit Scanner App Context

## Purpose

This app is a real-time Bybit spot market scanner. It streams ticker, trade, and orderbook data, stores realtime state and rolling history in Redis, computes alert scores once per minute, broadcasts alerts to the web dashboard, and sends high-score alerts to Telegram.

## Current Runtime Entry Point

Use:

```powershell
python -u main.py
```

Dashboard:

```text
http://localhost:8000
```

Current main process starts:

- historical OHLCV loader;
- Bybit WebSocket streamer;
- FastAPI dashboard server;
- scanner loop;
- Telegram queue worker.

Do not use `app.py` as the production runner. `app.py` and `scanner.py` are older synchronous paths and do not represent the current alert system.

## Main Files

- `main.py`: orchestrator, scan loop, alert publishing, Telegram queue.
- `data_stream.py`: Bybit spot WebSocket ingestion.
- `storage.py`: Redis realtime/history writes and context reads.
- `analytics.py`: z-score, squeeze, absorption, relative strength.
- `web_server.py`: FastAPI dashboard and Redis Pub/Sub fanout.
- `config.py`: symbols, Redis settings, Telegram settings, scoring weights.
- `templates/index.html`: dashboard UI.

## Current Symbol Set

Configured in `config.py`:

```text
BTCUSDT
ETHUSDT
SOLUSDT
XRPUSDT
DOGEUSDT
SUIUSDT
PEPEUSDT
FETUSDT
RENDERUSDT
STXUSDT
```

Important: `1000PEPEUSDT` is invalid on Bybit spot WebSocket and was replaced with `PEPEUSDT`.

## Data Flow

```text
Bybit spot WS
  -> data_stream.py
  -> storage.py
  -> Redis realtime/history
  -> main.py scan loop
  -> Redis Pub/Sub scanner_alerts
  -> web_server.py
  -> browser dashboard

main.py high-score alerts
  -> asyncio Telegram queue
  -> Telegram Bot API
```

## Redis Schema

Realtime hash:

```text
realtime:{SYMBOL}
```

Expected fields:

```text
last_price   float
last_update  epoch milliseconds
minute_vol   float, reset after each scan cycle
total_cvd    float, cumulative trade delta
bid_depth    float, 0.5% bid-side depth
ask_depth    float, 0.5% ask-side depth
```

History lists:

```text
hist:price:{SYMBOL}
hist:vol:{SYMBOL}
```

Expected:

- max length: 200;
- price and volume lengths should match;
- updated once per scanner cycle by `RedisStorage.rollover_minute`;
- newest values are at list tail after current implementation.

Health keys:

```text
health:heartbeat:Engine
health:heartbeat:Streamer
system:metrics
```

Alert Pub/Sub channel:

```text
scanner_alerts
```

Note: Redis Pub/Sub is not durable. If dashboard is offline, Pub/Sub alerts are lost.

## Alert Generation

`main.py::scan_symbol`:

1. Reads Redis context.
2. Applies wash trading filter:

```python
volume / (bid_depth + ask_depth) <= WASH_TRADING_RATIO
```

3. Calculates:
   - volume z-score;
   - Bollinger squeeze;
   - absorption;
   - relative strength versus BTC.
4. Builds total score using `SCORING_WEIGHTS`.
5. Emits alert if `score > 0`.

Alert payload:

```json
{
  "symbol": "XRPUSDT",
  "score": 53.71,
  "price": 1.412,
  "reasoning": ["Squeeze"],
  "timestamp": 1778932343000,
  "debug": {
    "latency": 0,
    "raw_values": {},
    "filter_status": []
  }
}
```

Timestamp must be Unix epoch milliseconds. If Redis contains old monotonic timestamps, `main.py` replaces them with current epoch milliseconds before publishing.

## Telegram Alerts

Config:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
TELEGRAM_MIN_SCORE default 100. Telegram sends alerts only when score is greater than this threshold.
```

Telegram is now non-blocking for the scan loop:

```text
scan loop -> enqueue_telegram_alert -> telegram_worker -> send_telegram_alert
```

Current limitations:

- no retry/backoff;
- no durable queue;
- no dedup/cooldown;
- no special handling for Telegram 429 `retry_after`.

## UI Notes

Dashboard receives alerts through WebSocket from `web_server.py`.

`Updated` should show current local date/time. If it shows 1970, Redis has bad `last_update` values or an old app process is still running.

Price formatting currently uses browser locale. Small-price symbols can look confusing. Example: `XRPUSDT` should be read as about `1.412 USDT`, not `$1,412`.

## Current Known Good State

Recent verification:

- Bybit spot WebSocket subscriptions succeed for all configured symbols.
- `last_update` writes epoch milliseconds after restart.
- Redis history lists are length 200.
- `DOGEUSDT`, `SUIUSDT`, `PEPEUSDT`, `FETUSDT` receive stream data.
- `RENDERUSDT` and `STXUSDT` can have low/no trades over short windows, but ticker/orderbook work.
- Scanner publishes alerts and dashboard receives them.

## Common Verification Commands

Check app processes:

```powershell
Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
  Where-Object { $_.CommandLine -match 'main\.py' } |
  Select-Object ProcessId,CommandLine
```

Stop app processes:

```powershell
Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
  Where-Object { $_.CommandLine -match 'main\.py' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

Check port 8000:

```powershell
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
```

Check Redis realtime:

```powershell
redis-cli HGETALL realtime:XRPUSDT
redis-cli HGETALL realtime:DOGEUSDT
redis-cli HGETALL realtime:PEPEUSDT
```

Check history:

```powershell
redis-cli LLEN hist:price:XRPUSDT
redis-cli LLEN hist:vol:XRPUSDT
redis-cli LRANGE hist:vol:XRPUSDT -10 -1
```

Expected realtime fields:

```text
last_price
last_update
minute_vol
total_cvd
bid_depth
ask_depth
```

## Trader Interpretation

Current `Squeeze` alert is a setup alert, not a standalone entry signal.

Trading interpretation:

```text
Squeeze alert -> watch range -> wait breakout -> confirm volume/direction -> decide entry
```

Do not treat `Squeeze` alone as buy/sell.

Useful next trading alert:

```text
Squeeze Breakout Confirmed
```

Suggested confirmation inputs:

- close outside local range;
- volume expansion;
- BTC direction filter;
- relative strength;
- orderbook imbalance.

## Known Technical Debt

High priority:

- Add retry/backoff for Telegram.
- Add Telegram dedup/cooldown.
- Add durable alert queue if alert loss matters.
- Add per-symbol stream health counters.
- Fix or remove absorption until CVD history is stored.

Medium priority:

- Improve dashboard price formatting by symbol tick size.
- Add subscription error counters to metrics.
- Make graceful shutdown await cancelled tasks.
- Close Redis/aiohttp resources explicitly.
- Avoid blocking `ccxt` calls in `web_server.py`.

## Development Rules

- Keep changes small and verify with Redis after each runtime change.
- Treat `main.py` as the real orchestrator.
- Do not restart multiple app instances on port 8000.
- After changing stream/storage logic, restart the app and wait at least one scan cycle.
- Always check Redis `last_update` format after changes; it must be epoch milliseconds.
- If a symbol has no `bid_depth` or `ask_depth`, alerts can be filtered out by wash trading logic.
