import redis.asyncio as redis
import logging
import asyncio
import time
from typing import Dict, Any, Optional
from config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD, logger

class RedisStorage:
    def __init__(self):
        try:
            self.redis = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                password=REDIS_PASSWORD,
                decode_responses=True
            )
            logger.info("Redis connection initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Redis connection: {e}")
            raise

    async def update_ticker(self, symbol: str, price: float) -> None:
        """Обновить last_price и last_update в хэше realtime:{symbol} используя Pipeline для атомарности"""
        key = f"realtime:{symbol}"
        timestamp = time.time() * 1000
        try:
            async with self.redis.pipeline() as pipe:
                pipe.hset(key, "last_price", price)
                pipe.hset(key, "last_update", timestamp)
                await pipe.execute()
            logger.debug(f"Updated ticker for {symbol}: price={price}")
        except Exception as e:
            logger.error(f"Failed to update ticker for {symbol}: {e}")
            raise

    async def update_trades(self, symbol: str, volume: float, side: str) -> None:
        """Атомарно инкрементировать minute_vol и обновить total_cvd в хэше, используя Pipeline"""
        key = f"realtime:{symbol}"
        cvd_change = volume if side.lower() == "buy" else -volume
        try:
            async with self.redis.pipeline() as pipe:
                pipe.hincrbyfloat(key, "minute_vol", volume)
                pipe.hincrbyfloat(key, "total_cvd", cvd_change)
                await pipe.execute()
            logger.debug(f"Updated trades for {symbol}: volume={volume}, side={side}, cvd_change={cvd_change}")
        except Exception as e:
            logger.error(f"Failed to update trades for {symbol}: {e}")
            raise

    async def update_orderbook(self, symbol: str, bid_depth_05: float, ask_depth_05: float) -> None:
        """Сохранить глубину ликвидности 0.5% в хэше realtime:{symbol}"""
        key = f"realtime:{symbol}"
        try:
            async with self.redis.pipeline() as pipe:
                pipe.hset(key, "bid_depth", bid_depth_05)
                pipe.hset(key, "ask_depth", ask_depth_05)
                await pipe.execute()
            logger.debug(f"Updated orderbook for {symbol}: bid={bid_depth_05}, ask={ask_depth_05}")
        except Exception as e:
            logger.error(f"Failed to update orderbook for {symbol}: {e}")
            raise

    async def update_liquidations(self, symbol: str, side: str, amount: float) -> None:
        """Инкрементировать rolling counter для ликвидаций в хэше"""
        key = f"realtime:{symbol}"
        counter_key = "liquidations"  # Или можно сделать отдельный ключ, но согласно заданию - в хэше
        try:
            async with self.redis.pipeline() as pipe:
                pipe.hincrbyfloat(key, counter_key, amount)
                await pipe.execute()
            logger.debug(f"Updated liquidations for {symbol}: side={side}, amount={amount}")
        except Exception as e:
            logger.error(f"Failed to update liquidations for {symbol}: {e}")
            raise

    async def push_history(self, symbol: str, price: float, volume: float) -> None:
        """Использовать Pipeline для lpush цены и объема в исторические списки и ltrim до 200 элементов"""
        price_key = f"hist:price:{symbol}"
        vol_key = f"hist:vol:{symbol}"
        try:
            async with self.redis.pipeline() as pipe:
                pipe.lpush(price_key, price)
                pipe.lpush(vol_key, volume)
                pipe.ltrim(price_key, 0, 199)  # Оставить только первые 200 элементов (новейшие)
                pipe.ltrim(vol_key, 0, 199)
                await pipe.execute()
            logger.debug(f"Pushed history for {symbol}: price={price}, volume={volume}")
        except Exception as e:
            logger.error(f"Failed to push history for {symbol}: {e}")
            raise

    async def rollover_minute(self, symbol: str) -> bool:
        """Append current realtime price/volume to history and reset minute volume atomically."""
        realtime_key = f"realtime:{symbol}"
        price_key = f"hist:price:{symbol}"
        vol_key = f"hist:vol:{symbol}"
        script = """
        local realtime_key = KEYS[1]
        local price_key = KEYS[2]
        local vol_key = KEYS[3]
        local price = redis.call('HGET', realtime_key, 'last_price')
        if not price then
            return 0
        end
        local volume = redis.call('HGET', realtime_key, 'minute_vol') or '0'
        redis.call('RPUSH', price_key, price)
        redis.call('RPUSH', vol_key, volume)
        redis.call('LTRIM', price_key, -200, -1)
        redis.call('LTRIM', vol_key, -200, -1)
        redis.call('HSET', realtime_key, 'minute_vol', '0')
        return 1
        """
        try:
            updated = await self.redis.eval(script, 3, realtime_key, price_key, vol_key)
            if updated:
                logger.debug(f"Rolled over minute history for {symbol}")
            return bool(updated)
        except Exception as e:
            logger.error(f"Failed to roll over minute history for {symbol}: {e}")
            raise

    async def get_context(self, symbol: str) -> Dict[str, Any]:
        """Использовать ОДИН Pipeline для получения всего хэша realtime и последних 200 элементов списков"""
        realtime_key = f"realtime:{symbol}"
        price_key = f"hist:price:{symbol}"
        vol_key = f"hist:vol:{symbol}"
        try:
            async with self.redis.pipeline() as pipe:
                pipe.hgetall(realtime_key)
                pipe.lrange(price_key, 0, 199)  # Получить первые 200 (новейшие)
                pipe.lrange(vol_key, 0, 199)
                results = await pipe.execute()

            realtime_data = results[0]
            price_data = [float(p) for p in results[1]]
            vol_data = [float(v) for v in results[2]]

            # Конвертировать realtime_data в подходящие типы
            context = {
                "realtime": {},
                "prices": price_data,
                "volumes": vol_data
            }
            for k, v in realtime_data.items():
                if k in ["last_price", "bid_depth", "ask_depth", "minute_vol", "total_cvd", "liquidations"]:
                    context["realtime"][k] = float(v)
                elif k == "last_update":
                    context["realtime"][k] = float(v)
                else:
                    context["realtime"][k] = v

            logger.debug(f"Retrieved context for {symbol}")
            return context
        except Exception as e:
            logger.error(f"Failed to get context for {symbol}: {e}")
            raise
