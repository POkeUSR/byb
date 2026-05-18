import redis.asyncio as redis
import time
from config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD, logger

class SystemMonitor:
    def __init__(self):
        self.redis = redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD,
            decode_responses=True
        )
        self.start_time = time.time()  # Для uptime

    async def heartbeat(self, process_name: str):
        """Отправляет heartbeat для процесса: устанавливает timestamp в Redis с TTL 120 секунд"""
        key = f"health:heartbeat:{process_name}"
        timestamp = time.time()
        await self.redis.setex(key, 120, timestamp)
        logger.debug(f"Heartbeat sent for {process_name}")

    async def set_metric(self, metric_name: str, value):
        """Устанавливает метрику производительности в Redis Hash system:metrics"""
        await self.redis.hset("system:metrics", metric_name, value)
        logger.debug(f"Metric set: {metric_name} = {value}")

    async def get_all_heartbeats(self):
        """Получает все heartbeat timestamps из Redis"""
        keys = await self.redis.keys("health:heartbeat:*")
        heartbeats = {}
        for key in keys:
            process_name = key.split(":")[-1]
            timestamp = await self.redis.get(key)
            if timestamp:
                heartbeats[process_name] = float(timestamp)
        return heartbeats

    async def get_all_metrics(self):
        """Получает все метрики из Redis Hash"""
        return await self.redis.hgetall("system:metrics")

    def get_uptime(self):
        """Возвращает uptime в секундах"""
        return time.time() - self.start_time