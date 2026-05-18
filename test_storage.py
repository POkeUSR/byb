import unittest
from unittest.mock import AsyncMock, patch
import asyncio
from storage import RedisStorage

class TestRedisStorage(unittest.TestCase):

    def setUp(self):
        self.storage = RedisStorage()
        self.storage.redis = AsyncMock()

    async def async_test_update_ticker(self):
        await self.storage.update_ticker('BTCUSDT', 50000.0)
        self.storage.redis.setex.assert_called()
        self.storage.redis.hset.assert_called_with('realtime:BTCUSDT', 'last_price', 50000.0)

    async def async_test_get_context(self):
        self.storage.redis.hgetall.return_value = {'last_price': '50000'}
        self.storage.redis.lrange.side_effect = [['50000'], ['1000']]
        context = await self.storage.get_context('BTCUSDT')
        self.assertIn('realtime', context)
        self.assertIn('prices', context)

    def test_update_ticker(self):
        asyncio.run(self.async_test_update_ticker())

    def test_get_context(self):
        asyncio.run(self.async_test_get_context())

if __name__ == '__main__':
    unittest.main()