import asyncio
import websockets
import json
import logging
from typing import List, Dict, Any
from config import SYMBOLS, logger
from storage import RedisStorage
from monitor import SystemMonitor

class BybitDataStream:
    def __init__(self):
        self.uri = "wss://stream.bybit.com/v5/public/spot"
        self.storage = RedisStorage()
        self.monitor = SystemMonitor()
        self.symbols = SYMBOLS
        self.reconnect_delay = 1
        self.max_reconnect_delay = 60
        self.message_count = 0

    async def subscribe_topics(self, websocket):
        """Subscribe per symbol so one invalid symbol does not reject unrelated topics."""
        subscribed_topics = 0
        for symbol in self.symbols:
            topics = [
                f"tickers.{symbol}",
                f"publicTrade.{symbol}",
                f"orderbook.50.{symbol}"
            ]
            subscribe_msg = {
                "op": "subscribe",
                "args": topics
            }
            await websocket.send(json.dumps(subscribe_msg))
            subscribed_topics += len(topics)
            logger.info(f"Subscribe requested for {symbol}: {len(topics)} topics")
            await asyncio.sleep(0.1)

        logger.info(f"Total subscribe requested for {subscribed_topics} topics across {len(self.symbols)} symbols")

    async def process_ticker(self, topic: str, data: Dict[str, Any]):
        """Обработать данные тикера: извлечь lastPrice и обновить в storage"""
        symbol = topic.split('.')[-1].upper()
        if "lastPrice" in data:
            last_price = float(data["lastPrice"])
            await self.storage.update_ticker(symbol, last_price)
            logger.debug(f"Processed ticker for {symbol}: {last_price}")

    async def process_public_trade(self, topic: str, data: List[Dict[str, Any]]):
        """Обработать публичные сделки: для каждой извлечь volume и side, обновить trades"""
        symbol = topic.split('.')[-1].upper()
        for trade in data:
            volume = float(trade["v"])
            side = trade["S"]
            await self.storage.update_trades(symbol, volume, side)
            logger.debug(f"Processed trade for {symbol}: vol={volume}, side={side}")

    async def process_orderbook(self, topic: str, data: Dict[str, Any]):
        """Обработать ордербук: рассчитать глубину ликвидности в 0.5% от lastPrice"""
        symbol = topic.split('.')[-1].upper()
        bids = data.get("b", [])
        asks = data.get("a", [])

        if not bids or not asks:
            logger.debug(f"No bids/asks for {symbol}")
            return

        # Получить lastPrice из Redis
        realtime_key = f"realtime:{symbol}"
        realtime_data = await self.storage.redis.hgetall(realtime_key)
        last_price = realtime_data.get("last_price")

        if last_price:
            last_price = float(last_price)
        else:
            # Если нет, использовать первую bid цену как референс
            last_price = float(bids[0][0])
            logger.debug(f"Using bid price as reference for {symbol}: {last_price}")

        # Рассчитать порог 0.5%
        bid_threshold = last_price * 0.995
        ask_threshold = last_price * 1.005

        # Суммировать size для bids >= bid_threshold и asks <= ask_threshold
        bid_depth = sum(float(size) for price, size in bids if float(price) >= bid_threshold)
        ask_depth = sum(float(size) for price, size in asks if float(price) <= ask_threshold)

        await self.storage.update_orderbook(symbol, bid_depth, ask_depth)
        logger.debug(f"Processed orderbook for {symbol}: bid_depth={bid_depth}, ask_depth={ask_depth}")



    async def handle_message(self, message: str):
        """Обработать входящее сообщение от WebSocket"""
        try:
            data = json.loads(message)
            topic = data.get("topic", "")
            payload = data.get("data", {})
            if data.get("success") is False:
                logger.error(f"Bybit subscription/control error: {data}")
                return
            if data.get("op") == "subscribe":
                logger.info(f"Bybit subscription response: {data}")
                return

            logger.debug(f"Received message for topic: {topic}")
            self.message_count += 1

            if topic.startswith("tickers."):
                await self.process_ticker(topic, payload)
            elif topic.startswith("publicTrade."):
                await self.process_public_trade(topic, payload)
            elif topic.startswith("orderbook.50."):
                await self.process_orderbook(topic, payload)
            else:
                logger.debug(f"Unhandled topic: {topic}")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse message: {e}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    async def ping_loop(self, websocket):
        """Отправлять ping каждые 20 секунд для поддержания соединения"""
        last_minute_count = 0
        while True:
            await asyncio.sleep(10)
            try:
                await websocket.send(json.dumps({"op": "ping"}))
                logger.debug("Sent ping")
                # Heartbeat каждые 10 секунд
                await self.monitor.heartbeat("Streamer")
                # Метрика сообщений в минуту
                messages_per_minute = (self.message_count - last_minute_count) * 6  # *6 для в минуту
                await self.monitor.set_metric("msgs_per_sec", messages_per_minute / 60)
                last_minute_count = self.message_count
            except Exception:
                logger.debug("Ping failed, connection likely closed")
                break

    async def run(self):
        """Основной цикл стриминга с авто-реконнектом"""
        while True:
            try:
                async with websockets.connect(self.uri) as websocket:
                    logger.info("Connected to Bybit WebSocket")
                    await self.subscribe_topics(websocket)

                    # Запустить ping loop
                    ping_task = asyncio.create_task(self.ping_loop(websocket))

                    # Обработка сообщений
                    async for message in websocket:
                        await self.handle_message(message)

                    # Отменить ping при закрытии соединения
                    ping_task.cancel()
                    try:
                        await ping_task
                    except asyncio.CancelledError:
                        pass
                    logger.warning("WebSocket connection closed")

            except websockets.exceptions.ConnectionClosed:
                logger.warning("Connection closed, reconnecting...")
            except Exception as e:
                logger.error(f"WebSocket error: {e}")

            # Экспоненциальная задержка
            await asyncio.sleep(self.reconnect_delay)
            self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)

if __name__ == "__main__":
    stream = BybitDataStream()
    asyncio.run(stream.run())
