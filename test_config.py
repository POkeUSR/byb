import unittest
import config

class TestConfig(unittest.TestCase):

    def test_symbols(self):
        """Проверка списка символов: тип, наличие данных и формат Bybit."""
        self.assertIsInstance(config.SYMBOLS, list)
        # Проверяем, что список не пуст
        self.assertGreater(len(config.SYMBOLS), 0, "Список SYMBOLS не должен быть пустым")
        
        for symbol in config.SYMBOLS:
            self.assertIsInstance(symbol, str)
            self.assertGreater(len(symbol), 0)
            # Важно для Bybit: символ должен заканчиваться на USDT
            self.assertTrue(
                symbol.endswith('USDT'), 
                f"Символ {symbol} имеет неверный формат. Ожидался суффикс USDT (например, BTCUSDT)"
            )

    def test_scoring_weights(self):
        """Проверка структуры и значений весов скоринга."""
        weights = config.SCORING_WEIGHTS
        self.assertIsInstance(weights, dict)
        
        expected_keys = ['z_score', 'relative_strength', 'absorption', 'squeeze']
        self.assertEqual(set(weights.keys()), set(expected_keys))
        
        # Сумма весов должна быть равна 1.0 (100%)
        total = sum(weights.values())
        self.assertAlmostEqual(total, 1.0, places=5, msg="Сумма весов в SCORING_WEIGHTS должна быть равна 1.0")
        
        for key, value in weights.items():
            self.assertIsInstance(value, float)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_beta_coefficient_thresholds(self):
        """Проверка пороговых значений коэффициента Бета."""
        thresh = config.BETA_COEFFICIENT_THRESHOLDS
        self.assertIsInstance(thresh, dict)
        
        expected_keys = ['decoupling_high', 'decoupling_low', 'neutral_high', 'neutral_low']
        self.assertEqual(set(thresh.keys()), set(expected_keys))
        
        for key, value in thresh.items():
            self.assertIsInstance(value, float)
            self.assertGreater(value, 0)

        # Логическая проверка иерархии значений
        self.assertGreater(thresh['decoupling_high'], thresh['neutral_high'])
        self.assertGreater(thresh['neutral_high'], thresh['neutral_low'])
        self.assertGreater(thresh['neutral_low'], thresh['decoupling_low'])

    def test_redis_settings(self):
        """Проверка настроек Redis."""
        self.assertIsInstance(config.REDIS_HOST, str)
        self.assertIsInstance(config.REDIS_PORT, int)
        self.assertGreater(config.REDIS_PORT, 0)
        self.assertLess(config.REDIS_PORT, 65536)
        self.assertIsInstance(config.REDIS_DB, int)
        self.assertGreaterEqual(config.REDIS_DB, 0)
        # Пароль может быть либо строкой, либо None
        self.assertTrue(isinstance(config.REDIS_PASSWORD, (str, type(None))))

    def test_bybit_api_settings(self):
        """Проверка настроек Bybit API."""
        # Ключи могут быть None (если не заданы в env) или строками
        self.assertTrue(isinstance(config.BYBIT_API_KEY, (str, type(None))))
        self.assertTrue(isinstance(config.BYBIT_API_SECRET, (str, type(None))))
        self.assertIsInstance(config.BYBIT_TESTNET, bool)

    def test_logging_settings(self):
        """Проверка настроек логирования."""
        self.assertIsInstance(config.LOG_LEVEL, str)
        self.assertIn(config.LOG_LEVEL, ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'])
        self.assertIsInstance(config.LOG_FORMAT, str)
        self.assertIsInstance(config.LOG_FILE, str)
        self.assertTrue(config.LOG_FILE.endswith('.log'))

if __name__ == '__main__':
    unittest.main()