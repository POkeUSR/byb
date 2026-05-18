import asyncio
import websockets
import json
import logging
import time
import base64
import binascii
import html
import re
import socket
from pathlib import Path
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import redis.asyncio as redis
import ccxt
import aiohttp
from config import (
    REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD,
    BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_TESTNET,
    OPENAI_API_KEY, OPENAI_VISUAL_MODEL, logger
)
from monitor import SystemMonitor
from config import SYMBOLS

app = FastAPI()
SCREENSHOT_ROOT = Path("screenshots")
VISUAL_TIMEFRAMES = ("5m", "15m", "1h")
TRADER_DESCRIPTION_FILE = Path("trader.txt")
SYMBOLS_DESCRIPTION_FILE = Path("symbols.txt")
TRADER_DESCRIPTION_LANGUAGES = {
    "en": ("English", Path("trader.txt")),
    "de": ("Deutsch", Path("trader_de.txt")),
    "ru": ("Русский", Path("trader_ru.txt")),
    "zh": ("中文", Path("trader_zh.txt")),
    "vi": ("Tiếng Việt", Path("trader_vi.txt")),
}

# Redis connection
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    password=REDIS_PASSWORD,
    decode_responses=True
)

monitor = SystemMonitor()
exchange = ccxt.bybit({
    'apiKey': BYBIT_API_KEY,
    'secret': BYBIT_API_SECRET,
    'enableRateLimit': True,
    'testnet': BYBIT_TESTNET,
})

# Active WebSocket connections
connections = set()

def safe_symbol(symbol: str) -> str:
    """Normalize user-provided symbol for folder names and prompts."""
    cleaned = re.sub(r"[^A-Z0-9_:-]", "", symbol.upper().strip())
    return cleaned.replace(":", "_")

def decode_png_data_url(data_url: str) -> bytes:
    if not data_url.startswith("data:image/png;base64,"):
        raise ValueError("Only PNG screenshots are accepted")
    try:
        return base64.b64decode(data_url.split(",", 1)[1], validate=True)
    except binascii.Error as exc:
        raise ValueError("Invalid PNG payload") from exc

async def analyze_chart_screenshots(symbol: str, images: dict) -> dict:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    content = [
        {
            "type": "input_text",
            "text": (
                "Analyze TradingView screenshots for a spot crypto scanner alert. "
                "The screenshots are 5m, 15m, and 1h timeframes for the same symbol. "
                "Do not provide financial advice. Act as a chart structure analyst. "
                "Return valid compact JSON only. Do not wrap it in markdown. Use keys: symbol, visual_status "
                "(CONFIRMED|WAIT|REJECTED), entry_quality (A|B|C), risk "
                "(LOW|MEDIUM|HIGH), trend_5m, trend_15m, trend_1h, reasons, "
                "invalid_if, next_action, summary_ru, summary_en. "
                "summary_ru must be a clear Russian explanation for a spot trader. "
                "summary_en must contain the same meaning in English. "
                "Keep reasons as a short array of concrete observations."
            )
        }
    ]
    for timeframe in VISUAL_TIMEFRAMES:
        content.append({
            "type": "input_text",
            "text": f"{symbol} {timeframe} screenshot"
        })
        content.append({
            "type": "input_image",
            "image_url": images[timeframe]
        })

    payload = {
        "model": OPENAI_VISUAL_MODEL,
        "input": [
            {
                "role": "user",
                "content": content
            }
        ],
        "temperature": 0.1,
        "max_output_tokens": 1200
    }

    timeout = aiohttp.ClientTimeout(total=60)
    connector = aiohttp.TCPConnector(
        resolver=aiohttp.ThreadedResolver(),
        family=socket.AF_INET
    )
    response_data = None
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        for attempt in range(1, 4):
            async with session.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json=payload
            ) as response:
                response_data = await response.json(content_type=None)
                if response.status < 400:
                    break

                message = response_data.get("error", {}).get("message", str(response_data))
                request_id = response.headers.get("x-request-id") or response_data.get("request_id", "")
                is_retryable = response.status in {429, 500, 502, 503, 504}
                logger.warning(
                    f"OpenAI visual request failed attempt={attempt} "
                    f"status={response.status} request_id={request_id}: {message}"
                )
                if not is_retryable or attempt == 3:
                    raise RuntimeError(
                        f"OpenAI API error {response.status}: {message}"
                        + (f" request_id={request_id}" if request_id else "")
                    )
                await asyncio.sleep(1.5 * attempt)

    text_parts = []
    for item in response_data.get("output", []):
        for part in item.get("content", []):
            if part.get("type") == "output_text":
                text_parts.append(part.get("text", ""))

    result_text = "\n".join(text_parts).strip()
    return {
        "model": OPENAI_VISUAL_MODEL,
        "analysis": result_text,
        "raw_id": response_data.get("id")
    }

async def broadcast(message: str):
    """Broadcast message to all connected WebSocket clients."""
    disconnected = set()
    for ws in connections:
        try:
            await ws.send_text(message)
        except Exception as e:
            logger.warning(f"Failed to send to client: {e}")
            disconnected.add(ws)
    connections.difference_update(disconnected)

async def pubsub_listener():
    """Listen to Redis Pub/Sub channel and broadcast messages."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe('scanner_alerts')
    logger.info("Web server subscribed to scanner_alerts channel")
    try:
        async for message in pubsub.listen():
            if message['type'] == 'message':
                logger.info(f"Broadcasting alert: {message['data'][:100]}...")
                await broadcast(message['data'])
    except Exception as e:
        logger.error(f"PubSub listener error: {e}")

async def get_current_prices():
    """Get current prices for all symbols from Redis."""
    prices = {}
    for symbol in SYMBOLS:
        try:
            realtime = await monitor.redis.hgetall(f"realtime:{symbol}")
            price = realtime.get("last_price")
            if price:
                prices[symbol] = float(price)
        except Exception as e:
            logger.debug(f"Error getting price for {symbol}: {e}")
    return prices

async def build_health_report():
    """Build a scanner readiness and runtime health report."""
    now = time.time()
    report = {
        "generated_at": now,
        "overall_status": "OK",
        "checks": {},
        "metrics": {},
        "symbols": {
            "configured": len(SYMBOLS),
            "unique": len(set(SYMBOLS)),
            "duplicates": sorted({symbol for symbol in SYMBOLS if SYMBOLS.count(symbol) > 1}),
        },
        "redis": {},
        "realtime": {},
        "websocket_clients": len(connections),
        "recommendations": []
    }

    try:
        await redis_client.ping()
        report["redis"]["status"] = "OK"
    except Exception as e:
        report["redis"]["status"] = "FAIL"
        report["redis"]["error"] = str(e)
        report["overall_status"] = "FAIL"

    heartbeats = await monitor.get_all_heartbeats()
    metrics = await monitor.get_all_metrics()
    report["heartbeats"] = heartbeats
    report["metrics"] = metrics

    for process_name in ("Streamer", "Engine"):
        timestamp = heartbeats.get(process_name)
        age = now - timestamp if timestamp else None
        ok = age is not None and age < 120
        report["checks"][process_name.lower()] = {
            "status": "OK" if ok else "FAIL",
            "age_seconds": round(age, 2) if age is not None else None
        }
        if not ok:
            report["overall_status"] = "FAIL"
            report["recommendations"].append(f"{process_name} heartbeat is stale or missing.")

    loop_latency = float(metrics.get("loop_latency_ms", 0) or 0)
    msgs_per_sec = float(metrics.get("msgs_per_sec", 0) or 0)
    report["checks"]["loop_latency"] = {
        "status": "OK" if loop_latency < 10000 else "WARN",
        "value_ms": loop_latency
    }
    report["checks"]["messages"] = {
        "status": "OK" if msgs_per_sec > 0 else "WARN",
        "msgs_per_sec": msgs_per_sec
    }
    if loop_latency >= 10000:
        report["overall_status"] = "WARN" if report["overall_status"] == "OK" else report["overall_status"]
        report["recommendations"].append("loop_latency_ms is high for realtime scanning.")

    fresh_count = 0
    stale_symbols = []
    missing_symbols = []
    for symbol in SYMBOLS:
        realtime = await redis_client.hgetall(f"realtime:{symbol}")
        last_update = float(realtime.get("last_update", 0) or 0)
        if last_update > 1_000_000_000_000:
            last_update = last_update / 1000
        age = now - last_update if last_update else None
        if age is None:
            missing_symbols.append(symbol)
        elif age < 180:
            fresh_count += 1
        else:
            stale_symbols.append(symbol)

    report["realtime"] = {
        "fresh_symbols": fresh_count,
        "missing_symbols": missing_symbols,
        "stale_symbols": stale_symbols,
        "fresh_ratio": round(fresh_count / len(SYMBOLS), 3) if SYMBOLS else 0
    }
    if fresh_count < max(1, int(len(SYMBOLS) * 0.7)):
        report["overall_status"] = "WARN" if report["overall_status"] == "OK" else report["overall_status"]
        report["recommendations"].append("Less than 70% of symbols have fresh realtime data.")

    report["redis"]["memory"] = await redis_client.info("memory")
    report["redis"]["keyspace"] = await redis_client.info("keyspace")
    return report

async def status_broadcaster():
    """Broadcast system status every 5 seconds."""
    while True:
        try:
            heartbeats = await monitor.get_all_heartbeats()
            metrics = await monitor.get_all_metrics()
            uptime = monitor.get_uptime()
            prices = await get_current_prices()

            # Check Redis connectivity
            redis_status = "alive"
            try:
                await monitor.redis.ping()
            except:
                redis_status = "dead"

            status = {
                "type": "system_status",
                "heartbeats": heartbeats,
                "metrics": metrics,
                "uptime": uptime,
                "redis_status": redis_status,
                "last_update": time.time()
            }
            logger.debug(f"Sending system status with {len(prices)} prices")
            await broadcast(json.dumps(status))
        except Exception as e:
            logger.error(f"Status broadcast error: {e}")
        await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    """Start background tasks on app startup."""
    asyncio.create_task(pubsub_listener())
    asyncio.create_task(status_broadcaster())
    logger.info("Web server started with PubSub and status broadcasting")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await websocket.accept()
    connections.add(websocket)
    logger.info(f"WebSocket client connected. Total clients: {len(connections)}")
    try:
        while True:
            # Keep connection alive, receive any client messages if needed
            data = await websocket.receive_text()
            # Echo back or ignore
            await websocket.send_text(f"Echo: {data}")
    except Exception as e:
        logger.info(f"WebSocket client disconnected: {e}")
    finally:
        connections.remove(websocket)
        logger.info(f"WebSocket client removed. Total clients: {len(connections)}")

@app.get("/")
async def read_root():
    """Serve the index.html file."""
    return FileResponse("templates/index.html", headers={"Cache-Control": "no-store"})

@app.get("/visual-check")
async def visual_check_page():
    """Serve the manual TradingView screenshot analyzer page."""
    return FileResponse("templates/visual_check.html")

@app.get("/api/health-report")
async def health_report_api():
    """Return machine-readable runtime health report."""
    return await build_health_report()

@app.get("/health-report")
async def health_report_page():
    """Serve a readable scanner health report page."""
    report = await build_health_report()
    status_class = {
        "OK": "ok",
        "WARN": "warn",
        "FAIL": "fail"
    }.get(report["overall_status"], "warn")
    stale_preview = ", ".join(report["realtime"]["stale_symbols"][:20]) or "none"
    missing_preview = ", ".join(report["realtime"]["missing_symbols"][:20]) or "none"
    recommendations = report["recommendations"] or ["No immediate action required."]
    recommendations_html = "".join(f"<li>{html.escape(item)}</li>" for item in recommendations)
    checks_html = "".join(
        f"""
        <div class="card">
            <div class="label">{html.escape(name)}</div>
            <div class="value {html.escape(str(check.get('status', '')).lower())}">{html.escape(str(check.get('status', 'N/A')))}</div>
            <pre>{html.escape(json.dumps(check, indent=2))}</pre>
        </div>
        """
        for name, check in report["checks"].items()
    )
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Health Report</title>
    <style>
        :root {{
            --bg: #050505;
            --panel: rgba(0, 18, 20, 0.86);
            --accent: #00f3ff;
            --text: #e0e0e0;
            --muted: #7c8b91;
            --border: rgba(0, 243, 255, 0.22);
            --success: #00ff9d;
            --warning: #eab308;
            --error: #ff4d5e;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            min-height: 100vh;
            background: linear-gradient(120deg, rgba(0, 243, 255, 0.08), rgba(0, 255, 157, 0.04)), var(--bg);
            color: var(--text);
            font-family: Consolas, "JetBrains Mono", monospace;
        }}
        main {{
            width: min(1180px, calc(100% - 28px));
            margin: 0 auto;
            padding: 24px 0 48px;
        }}
        a {{ color: var(--accent); text-decoration: none; }}
        .top, .panel, .card {{
            border: 1px solid var(--border);
            background: var(--panel);
            box-shadow: 0 0 28px rgba(0, 243, 255, 0.08);
        }}
        .top {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            border-left: 2px solid var(--accent);
            padding: 16px;
            margin-bottom: 14px;
        }}
        h1 {{ margin: 0; text-transform: uppercase; }}
        .status {{ font-size: 28px; font-weight: 700; }}
        .ok {{ color: var(--success); }}
        .warn {{ color: var(--warning); }}
        .fail {{ color: var(--error); }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 14px;
            margin-bottom: 14px;
        }}
        .panel, .card {{ padding: 14px; }}
        .label {{ color: var(--muted); font-size: 11px; text-transform: uppercase; }}
        .value {{ margin-top: 6px; color: #fff; font-size: 20px; font-weight: 700; }}
        pre {{
            white-space: pre-wrap;
            overflow: auto;
            color: var(--muted);
            font-size: 12px;
        }}
        ul {{ margin: 8px 0 0; padding-left: 18px; }}
        @media (max-width: 920px) {{ .grid {{ grid-template-columns: 1fr; }} .top {{ flex-direction: column; align-items: flex-start; }} }}
    </style>
</head>
<body>
    <main>
        <div class="top">
            <div>
                <h1>Health Report</h1>
                <div class="label">Generated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(report["generated_at"]))}</div>
            </div>
            <div class="status {status_class}">{html.escape(report["overall_status"])}</div>
        </div>
        <section class="grid">
            <div class="panel"><div class="label">Symbols</div><div class="value">{report["symbols"]["configured"]}</div></div>
            <div class="panel"><div class="label">Fresh Realtime</div><div class="value">{report["realtime"]["fresh_symbols"]}</div></div>
            <div class="panel"><div class="label">Msgs/sec</div><div class="value">{html.escape(str(report["metrics"].get("msgs_per_sec", "0")))}</div></div>
            <div class="panel"><div class="label">Loop Latency</div><div class="value">{html.escape(str(report["metrics"].get("loop_latency_ms", "0")))} ms</div></div>
        </section>
        <section class="grid">
            {checks_html}
        </section>
        <section class="panel">
            <div class="label">Recommendations</div>
            <ul>{recommendations_html}</ul>
        </section>
        <section class="grid" style="margin-top: 14px;">
            <div class="panel"><div class="label">Missing Symbols</div><pre>{html.escape(missing_preview)}</pre></div>
            <div class="panel"><div class="label">Stale Symbols</div><pre>{html.escape(stale_preview)}</pre></div>
            <div class="panel"><div class="label">Redis Memory</div><pre>{html.escape(str(report["redis"].get("memory", {}).get("used_memory_human", "N/A")))}</pre></div>
            <div class="panel"><div class="label">Clients</div><pre>{report["websocket_clients"]}</pre></div>
        </section>
        <section class="panel" style="margin-top: 14px;">
            <div class="label">Raw JSON</div>
            <pre>{html.escape(json.dumps(report, indent=2))}</pre>
        </section>
    </main>
</body>
</html>""")

@app.get("/trader-description")
async def trader_description_page():
    """Serve a readable trader description page from trader.txt."""
    return await trader_description_language_page("en")

@app.get("/trader-description/{language}")
async def trader_description_language_page(language: str):
    """Serve a readable trader description page in the requested language."""
    language = language.lower()
    if language not in TRADER_DESCRIPTION_LANGUAGES:
        language = "en"

    language_label, source_file = TRADER_DESCRIPTION_LANGUAGES[language]
    try:
        text = source_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = f"{source_file} not found"

    escaped_text = html.escape(text)
    try:
        observed_symbols = [
            line.strip()
            for line in SYMBOLS_DESCRIPTION_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    except FileNotFoundError:
        observed_symbols = SYMBOLS

    symbols_count = len(observed_symbols)
    symbols_html = "".join(
        f'<span class="symbol-chip">{html.escape(symbol)}</span>'
        for symbol in observed_symbols
    )
    language_links = "".join(
        f'<a class="neo-btn {"active" if code == language else ""}" href="/trader-description{"" if code == "en" else f"/{code}"}">{html.escape(label)}</a>'
        for code, (label, _) in TRADER_DESCRIPTION_LANGUAGES.items()
    )
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Описание сканера</title>
    <style>
        :root {{
            --bg: #050505;
            --panel: rgba(0, 18, 20, 0.86);
            --panel-strong: rgba(0, 12, 14, 0.96);
            --accent: #00f3ff;
            --text: #e0e0e0;
            --muted: #7c8b91;
            --border: rgba(0, 243, 255, 0.22);
            --success: #00ff9d;
        }}
        * {{
            box-sizing: border-box;
        }}
        body {{
            margin: 0;
            min-height: 100vh;
            background:
                linear-gradient(120deg, rgba(0, 243, 255, 0.08), rgba(0, 255, 157, 0.045), rgba(234, 179, 8, 0.035), rgba(0, 243, 255, 0.06)),
                radial-gradient(circle at 20% 10%, rgba(0, 243, 255, 0.08), transparent 28rem),
                radial-gradient(circle at 80% 0%, rgba(0, 255, 157, 0.05), transparent 22rem),
                var(--bg);
            background-size: 260% 260%, auto, auto, auto;
            color: var(--text);
            font-family: Consolas, "JetBrains Mono", monospace;
            animation: soft-gradient-shift 28s ease-in-out infinite;
        }}
        body::before {{
            content: "";
            position: fixed;
            inset: 0;
            background:
                linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.14) 50%),
                linear-gradient(90deg, rgba(255, 0, 0, 0.03), rgba(0, 255, 0, 0.012), rgba(0, 0, 255, 0.03));
            background-size: 100% 2px, 3px 100%;
            pointer-events: none;
            z-index: 50;
        }}
        @keyframes soft-gradient-shift {{
            0%, 100% {{ background-position: 0% 50%, center, center, center; }}
            50% {{ background-position: 100% 50%, center, center, center; }}
        }}
        main {{
            width: min(1120px, calc(100% - 28px));
            margin: 0 auto;
            padding: 24px 0 48px;
        }}
        a {{
            color: var(--accent);
            text-decoration: none;
        }}
        .top {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 16px;
            margin-bottom: 16px;
            border: 1px solid var(--border);
            border-left: 2px solid var(--accent);
            background: var(--panel);
            padding: 16px;
            box-shadow: 0 0 28px rgba(0, 243, 255, 0.08);
        }}
        .panel {{
            border: 1px solid var(--border);
            background: var(--panel);
            box-shadow: 0 0 28px rgba(0, 243, 255, 0.08);
        }}
        h1 {{
            margin: 0;
            color: #fff;
            font-size: clamp(24px, 4vw, 42px);
            line-height: 1;
            text-transform: uppercase;
            letter-spacing: 0;
        }}
        .sub {{
            margin: 7px 0 0;
            color: var(--muted);
            font-size: 12px;
            text-transform: uppercase;
        }}
        .neo-btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 40px;
            border: 1px solid var(--accent);
            background: rgba(0, 243, 255, 0.08);
            padding: 0 14px;
            color: var(--accent);
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            box-shadow: inset 0 0 10px rgba(0, 243, 255, 0.08);
        }}
        .neo-btn.active {{
            border-color: var(--success);
            color: var(--success);
            background: rgba(0, 255, 157, 0.12);
        }}
        .language-bar {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 14px;
            border: 1px solid var(--border);
            background: var(--panel);
            padding: 12px;
            box-shadow: 0 0 28px rgba(0, 243, 255, 0.08);
        }}
        .symbols-panel {{
            margin-top: 14px;
            border: 1px solid var(--border);
            border-left: 2px solid var(--accent);
            background: var(--panel);
            padding: 16px;
            box-shadow: 0 0 28px rgba(0, 243, 255, 0.08);
        }}
        .symbols-head {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            margin-bottom: 12px;
            color: #fff;
            text-transform: uppercase;
        }}
        .symbols-count {{
            color: var(--success);
            font-size: 12px;
        }}
        .symbols-grid {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .symbol-chip {{
            border: 1px solid var(--border);
            background: rgba(0, 0, 0, 0.28);
            padding: 6px 8px;
            color: var(--accent);
            font-size: 12px;
        }}
        pre {{
            white-space: pre-wrap;
            line-height: 1.6;
            border: 1px solid var(--border);
            border-left: 2px solid var(--success);
            background: var(--panel);
            padding: 18px 20px;
            overflow: auto;
            box-shadow: 0 0 28px rgba(0, 243, 255, 0.08);
            font-size: 14px;
        }}
        @media (max-width: 720px) {{
            .top {{
                align-items: flex-start;
                flex-direction: column;
            }}
        }}
    </style>
</head>
<body>
    <main>
        <div class="top">
            <div>
                <h1>Scanner Description</h1>
                <p class="sub">BYBIT_SPOT_SCANNER_V1 // trader guide // {html.escape(language_label)}</p>
            </div>
            <a class="neo-btn" href="/">Dashboard</a>
        </div>
        <nav class="language-bar" aria-label="Language translations">
            {language_links}
        </nav>
        <pre>{escaped_text}</pre>
        <section class="symbols-panel">
            <div class="symbols-head">
                <span>Observed Symbols</span>
                <span class="symbols-count">{symbols_count} active</span>
            </div>
            <div class="symbols-grid">
                {symbols_html}
            </div>
        </section>
    </main>
</body>
</html>""")

@app.post("/api/visual-check/analyze")
async def visual_check_analyze(request: Request):
    """Save 5m/15m/1h screenshots and send them to GPT visual analysis."""
    try:
        payload = await request.json()
        symbol = safe_symbol(payload.get("symbol", ""))
        images = payload.get("images", {})
        if not symbol:
            return JSONResponse({"error": "Symbol is required"}, status_code=400)

        missing = [timeframe for timeframe in VISUAL_TIMEFRAMES if not images.get(timeframe)]
        if missing:
            return JSONResponse({"error": f"Missing screenshots: {', '.join(missing)}"}, status_code=400)

        symbol_dir = SCREENSHOT_ROOT / symbol
        symbol_dir.mkdir(parents=True, exist_ok=True)

        stored = {}
        for timeframe in VISUAL_TIMEFRAMES:
            png_bytes = decode_png_data_url(images[timeframe])
            file_path = symbol_dir / f"{timeframe}.png"
            file_path.write_bytes(png_bytes)
            stored[timeframe] = str(file_path)

        logger.info(f"Visual analysis requested for {symbol}: saved {len(stored)} screenshots")
        result = await analyze_chart_screenshots(symbol, images)
        await redis_client.hset(
            f"visual:analysis:{symbol}",
            mapping={
                "symbol": symbol,
                "model": result["model"],
                "analysis": result["analysis"],
                "raw_id": result.get("raw_id") or "",
                "updated_at": str(time.time())
            }
        )

        return {
            "symbol": symbol,
            "stored": stored,
            **result
        }
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.exception(f"Visual analysis failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "clients": len(connections)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
