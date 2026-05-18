import unittest
from unittest.mock import patch
import ccxt
from history_loader import HistoryLoader

class TestHistoryLoader(unittest.TestCase):

    @patch('history_loader.redis.Redis')
    @patch('history_loader.ccxt.bybit')
    def setUp(self, mock_bybit, mock_redis):
        self.mock_redis_instance = mock_redis.return_value
        self.mock_exchange = mock_bybit.return_value
        self.loader = HistoryLoader()

    def test_fetch_and_store_history_success(self):
        """Test successful fetch and store."""
        mock_ohlcv = [
            [1609459200000, 29000, 29500, 28900, 29400, 1000],
            [1609459260000, 29400, 29600, 29300, 29500, 1100],
        ]
        self.mock_exchange.fetch_ohlcv.return_value = mock_ohlcv

        # Run async test
        import asyncio
        asyncio.run(self.loader.fetch_and_store_history('BTCUSDT'))

        # Check Redis operations
        self.mock_redis_instance.pipeline.assert_called()
        pipe_mock = self.mock_redis_instance.pipeline.return_value
        pipe_mock.rpush.assert_called()

    def test_load_all_histories(self):
        """Test loading all histories."""
        with patch.object(self.loader, 'fetch_and_store_history') as mock_fetch:
            import asyncio
            asyncio.run(self.loader.load_all_histories())

            # Should call fetch for symbols
            self.assertTrue(mock_fetch.called)

if __name__ == '__main__':
    unittest.main()