import unittest
from unittest.mock import patch, AsyncMock
import asyncio
from data_stream import BybitDataStream

class TestBybitDataStream(unittest.TestCase):

    def setUp(self):
        with patch('data_stream.redis.Redis'), patch('data_stream.ccxt.bybit'):
            self.streamer = BybitDataStream()

    async def async_test_subscribe(self):
        with patch('data_stream.websockets.connect') as mock_ws:
            mock_websocket = AsyncMock()
            mock_ws.return_value.__aenter__.return_value = mock_websocket
            await self.streamer.subscribe_topics(mock_websocket)
            mock_websocket.send.assert_called()

    def test_subscribe_topics(self):
        asyncio.run(self.async_test_subscribe())

if __name__ == '__main__':
    unittest.main()