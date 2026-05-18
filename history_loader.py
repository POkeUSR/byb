import redis
import ccxt
import logging
import asyncio
from config import (
    SYMBOLS, REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD,
    BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_TESTNET, logger
)

class HistoryLoader:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            decode_responses=True
        )
        self.exchange = ccxt.bybit({
            'apiKey': BYBIT_API_KEY,
            'secret': BYBIT_API_SECRET,
            'enableRateLimit': True,
            'testnet': BYBIT_TESTNET,
        })
        self.symbols = SYMBOLS

    async def fetch_and_store_history(self, symbol: str):
        """Fetch last 200 minutes of OHLCV data and store in Redis."""
        try:
            # Fetch 200 candles of 1m timeframe
            ohlcv = self.exchange.fetch_ohlcv(symbol, '1m', limit=200)
            if not ohlcv:
                logger.warning(f"No data fetched for {symbol}")
                return

            # Extract close prices and volumes
            prices = [candle[4] for candle in ohlcv]  # Close price
            volumes = [candle[5] for candle in ohlcv]  # Volume

            # Store in Redis lists
            price_key = f'hist:price:{symbol}'
            vol_key = f'hist:vol:{symbol}'

            # Clear existing data
            self.redis_client.delete(price_key)
            self.redis_client.delete(vol_key)

            # Push data to Redis lists
            self.redis_client.rpush(price_key, *prices)
            self.redis_client.rpush(vol_key, *volumes)

            logger.info(f"Stored {len(prices)} data points for {symbol}")

        except Exception as e:
            logger.error(f"Failed to fetch/store data for {symbol}: {e}")

    async def load_all_histories(self):
        """Load history for all symbols."""
        logger.info("Starting history loading for all symbols")
        for symbol in self.symbols:
            await self.fetch_and_store_history(symbol)
            # Small delay to respect rate limits
            await asyncio.sleep(0.1)
        logger.info("History loading completed")

if __name__ == '__main__':
    loader = HistoryLoader()
    loader.load_all_histories()
