import asyncio
import signal
import sys
import uvicorn
import time
from uvicorn import Server
import threading
import json
from html import escape
import aiohttp
from config import (
    SYMBOLS, WASH_TRADING_RATIO, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    TELEGRAM_MIN_SCORE, REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD
)
from config import main_logger

math_logger = main_logger
logger = main_logger
from storage import RedisStorage
from data_stream import BybitDataStream
from history_loader import HistoryLoader
from analytics import AnalyticsEngine
from intelligence import SignalIntelligenceEngine
from config import SCORING_WEIGHTS
from monitor import SystemMonitor
import redis.asyncio as redis

class CryptoScanner:
    def __init__(self):
        self.storage = RedisStorage()
        self.redis_pub = redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD,
            decode_responses=True
        )
        self.streamer = BybitDataStream()
        self.analytics = AnalyticsEngine()
        self.intelligence = SignalIntelligenceEngine()
        self.monitor = SystemMonitor()
        self.running = True
        self.telegram_queue = asyncio.Queue(maxsize=1000)
        self.confirmation_queue = asyncio.Queue(maxsize=1000)

    async def load_history(self):
        """Load historical data on startup."""
        loader = HistoryLoader()
        await loader.load_all_histories()

    async def send_telegram_alert(self, message: str):
        """Send alert to Telegram."""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.warning("Telegram not configured, skipping alert")
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        logger.error(f"Telegram send failed: {resp.status}")
            except Exception as e:
                logger.error(f"Telegram error: {e}")

    async def telegram_worker(self):
        """Send Telegram alerts outside the scan loop."""
        while True:
            message = await self.telegram_queue.get()
            try:
                await self.send_telegram_alert(message)
            finally:
                self.telegram_queue.task_done()

    def enqueue_telegram_alert(self, alert: dict):
        intelligence = alert.get("intelligence", {})
        symbol = str(alert.get("symbol", "UNKNOWN"))
        score = alert.get("score", 0)
        price = alert.get("price", 0)
        tier = intelligence.get("tier", "N/A")
        status = intelligence.get("signal_status", "N/A")
        risk = intelligence.get("risk_level", "N/A")
        trap_probability = intelligence.get("trap_probability")
        explanation = intelligence.get("explanation")
        reasons = alert.get("reasoning") or ["No reasoning tags"]
        if isinstance(reasons, (list, tuple, set)):
            reasons_text = ", ".join(str(reason) for reason in reasons)
        else:
            reasons_text = str(reasons)
        tradingview_url = f"https://www.tradingview.com/chart/?symbol=BYBIT:{symbol}"
        tradingview_link = escape(tradingview_url, quote=True)

        trap_line = ""
        if trap_probability is not None:
            trap_line = f"\nTrap: <b>{escape(str(trap_probability))}</b>"

        explanation_line = ""
        if explanation:
            explanation_line = f"\n\n{escape(str(explanation))}"

        message = (
            f"<b>HIGH ALERT</b>\n"
            f"<b>{escape(symbol)}</b> | Score: <b>{escape(str(score))}</b>\n"
            f"Price: <code>{escape(str(price))}</code>\n\n"
            f"Tier: <b>{escape(str(tier))}</b>\n"
            f"Status: <b>{escape(str(status))}</b>\n"
            f"Risk: <b>{escape(str(risk))}</b>"
            f"{trap_line}\n\n"
            f"Signals: {escape(reasons_text)}"
            f"{explanation_line}\n\n"
            f'<a href="{tradingview_link}">Open TradingView chart</a>'
        )
        try:
            self.telegram_queue.put_nowait(message)
            logger.info(f"Queued Telegram alert for {symbol} score={score}")
        except asyncio.QueueFull:
            logger.error(f"Telegram queue full, dropped alert for {symbol} score={score}")

    async def store_signal_analytics(self, alert: dict):
        payload = {
            "symbol": alert.get("symbol"),
            "score": alert.get("score"),
            "timestamp": alert.get("timestamp"),
            "reasoning": alert.get("reasoning", []),
            "intelligence": alert.get("intelligence", {}),
        }
        try:
            await self.redis_pub.xadd("signal_analytics", {"data": json.dumps(payload)}, maxlen=5000, approximate=True)
        except Exception as e:
            logger.error(f"Failed to store signal analytics for {alert.get('symbol')}: {e}")

    async def confirmation_worker(self):
        """Evaluate post-signal continuation without blocking raw alerts."""
        while True:
            alert = await self.confirmation_queue.get()
            try:
                asyncio.create_task(self.delayed_signal_confirmation(alert))
            finally:
                self.confirmation_queue.task_done()

    async def delayed_signal_confirmation(self, alert: dict):
        await asyncio.sleep(60)
        await self.evaluate_signal_confirmation(alert)

    def enqueue_confirmation(self, alert: dict):
        try:
            self.confirmation_queue.put_nowait(alert)
        except asyncio.QueueFull:
            logger.error(f"Confirmation queue full, dropped follow-up for {alert.get('symbol')}")

    async def evaluate_signal_confirmation(self, alert: dict):
        symbol = alert.get("symbol")
        entry_price = alert.get("price") or 0
        try:
            context = await self.storage.get_context(symbol)
            current_price = context.get("realtime", {}).get("last_price", 0)
            move_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price else 0
            trap_probability = alert.get("intelligence", {}).get("trap_probability", 0)

            if trap_probability >= 0.6 and move_pct < 0:
                outcome = "TRAP"
            elif move_pct >= 0.35:
                outcome = "CONFIRMED"
            elif move_pct <= -0.35:
                outcome = "FAILED"
            else:
                outcome = "UNRESOLVED"

            payload = {
                "symbol": symbol,
                "entry_price": entry_price,
                "current_price": current_price,
                "move_pct": round(move_pct, 4),
                "outcome": outcome,
                "source_timestamp": alert.get("timestamp"),
                "evaluated_at": time.time() * 1000,
                "tier": alert.get("intelligence", {}).get("tier"),
                "risk_level": alert.get("intelligence", {}).get("risk_level"),
            }
            await self.redis_pub.xadd("signal_confirmations", {"data": json.dumps(payload)}, maxlen=5000, approximate=True)
            logger.info(f"Signal confirmation {symbol}: {outcome} move={move_pct:.4f}%")
        except Exception as e:
            logger.error(f"Failed signal confirmation for {symbol}: {e}")

    async def scan_symbol(self, symbol: str, start_time: float) -> dict:
        """Scan a single symbol and return analysis."""
        context = await self.storage.get_context(symbol)
        if not context or not context['realtime']:
            return None

        realtime = context['realtime']
        prices = context['prices']
        volumes = context['volumes']
        cvds = [realtime.get('total_cvd', 0)]  # Simplified, ideally track CVD history

        # Apply Wash Trading Filter
        volume = realtime.get('minute_vol', 0)
        bid_depth = realtime.get('bid_depth', 0)
        ask_depth = realtime.get('ask_depth', 0)
        wash_filter_passed = not (bid_depth + ask_depth == 0 or volume / (bid_depth + ask_depth) > WASH_TRADING_RATIO)
        if not wash_filter_passed:
            logger.debug(f"Skipped {symbol} due to wash trading filter")
            return None

        # Calculate Metrics
        z_score = self.analytics.calculate_z_score(volumes)
        squeeze = self.analytics.detect_squeeze(prices)
        absorption = self.analytics.check_absorption(prices, cvds)

        # For relative strength, need BTC data
        btc_context = await self.storage.get_context('BTCUSDT')
        btc_prices = btc_context['prices'] if btc_context else prices
        rel_strength = self.analytics.get_relative_strength(prices, btc_prices)

        # Scoring
        score_z = (abs(z_score) if z_score else 0) * 100  # Normalize to 0-100
        score_squeeze = 100 if squeeze else 0
        score_absorption = 100 if absorption == "Bullish" else 0
        score_rs = max(0, min(100, (rel_strength + 1) * 50)) if rel_strength else 0  # Normalize

        total_score = (
            SCORING_WEIGHTS['z_score'] * score_z +
            SCORING_WEIGHTS['squeeze'] * score_squeeze +
            SCORING_WEIGHTS['absorption'] * score_absorption +
            SCORING_WEIGHTS['relative_strength'] * score_rs
        )

        latency = (asyncio.get_event_loop().time() - start_time) * 1000  # ms

        # Logic tags
        tags = []
        if squeeze:
            tags.append("Squeeze")
        if absorption == "Bullish":
            tags.append("Absorption")
        if z_score and abs(z_score) >= 2:
            tags.append("Volume Spike")
        elif z_score and abs(z_score) >= 1:
            tags.append("Volume Anomaly")
        if rel_strength and rel_strength > 0.05:
            tags.append("Strong vs BTC")
        elif rel_strength and rel_strength > 0:
            tags.append("Relative Strength")
        if not tags and total_score > 0:
            tags.append("Score Components")

        timestamp = realtime.get('last_update')
        if not timestamp or timestamp < 1_000_000_000_000:
            timestamp = time.time() * 1000

        return {
            'symbol': symbol,
            'score': round(total_score, 2),
            'price': realtime.get('last_price', 0),
            'reasoning': tags,
            'timestamp': timestamp,
            'debug': {
                'latency': round(latency, 2),
                'raw_values': {
                    'z_score': round(z_score, 2) if z_score else None,
                    'squeeze': int(squeeze),
                    'absorption': absorption,
                    'relative_strength': round(rel_strength, 4) if rel_strength else None
                },
                'filter_status': [int(wash_filter_passed), int(squeeze), int(absorption == "Bullish"), int(rel_strength > 0.05 if rel_strength else False)]
            }
        }

    async def main_loop(self):
        """Main scanning loop every 60 seconds."""
        while self.running:
            loop_start = asyncio.get_event_loop().time()
            logger.info("Starting scan cycle")
            alerts = []
            btc_context = await self.storage.get_context('BTCUSDT')
            for symbol in SYMBOLS:
                result = await self.scan_symbol(symbol, loop_start)
                if result and result['score'] > 0:
                    context = await self.storage.get_context(symbol)
                    alerts.append(self.intelligence.enrich(result, context, btc_context))

            # Sort by score descending
            alerts.sort(key=lambda x: x['score'], reverse=True)

            # Publish all alerts
            for alert in alerts:
                alert_json = json.dumps(alert)
                await self.redis_pub.publish('scanner_alerts', alert_json)
                await self.store_signal_analytics(alert)
                self.enqueue_confirmation(alert)

                # Telegram for high-score alerts only.
                if alert['score'] > TELEGRAM_MIN_SCORE:
                    self.enqueue_telegram_alert(alert)

            rolled_over = 0
            for symbol in SYMBOLS:
                try:
                    if await self.storage.rollover_minute(symbol):
                        rolled_over += 1
                except Exception:
                    logger.exception(f"Minute rollover failed for {symbol}")

            total_latency = (asyncio.get_event_loop().time() - loop_start) * 1000  # ms
            await self.monitor.heartbeat("Engine")
            await self.monitor.set_metric("loop_latency_ms", total_latency)

            logger.info(f"Scan cycle complete, published {len(alerts)} alerts, rolled over {rolled_over} symbols, total latency: {total_latency:.2f}ms")
            await asyncio.sleep(60)

    async def run(self):
        """Run the full scanner system."""
        # Load history
        await self.load_history()

        # Start streamer
        streamer_task = asyncio.create_task(self.streamer.run())
        telegram_task = asyncio.create_task(self.telegram_worker())
        confirmation_task = asyncio.create_task(self.confirmation_worker())

        # Start web server in separate thread
        def run_web_server():
            server = Server(uvicorn.Config("web_server:app", host="0.0.0.0", port=8000, log_level="info"))
            asyncio.run(server.serve())

        web_thread = threading.Thread(target=run_web_server, daemon=True)
        web_thread.start()

        # Handle shutdown
        def shutdown_handler(signum, frame):
            logger.info("Shutdown signal received")
            self.running = False

        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)

        try:
            await self.main_loop()
        except Exception as e:
            logger.error(f"Main loop error: {e}")
        finally:
            streamer_task.cancel()
            telegram_task.cancel()
            confirmation_task.cancel()
            await self.redis_pub.aclose()
            logger.info("Scanner shut down")

if __name__ == "__main__":
    scanner = CryptoScanner()
    asyncio.run(scanner.run())
