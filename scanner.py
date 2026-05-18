import time
import logging
from typing import Dict, List
import ccxt
from config import (
    SYMBOLS, BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_TESTNET,
    SCORING_WEIGHTS, BETA_COEFFICIENT_THRESHOLDS, logger
)

class CryptoScanner:
    def __init__(self):
        self.exchange = ccxt.bybit({
            'apiKey': BYBIT_API_KEY,
            'secret': BYBIT_API_SECRET,
            'enableRateLimit': True,
            'testnet': BYBIT_TESTNET,
        })
        self.symbols = [f'{symbol}USDT' for symbol in SYMBOLS if symbol != 'USDT']  # Assuming USDT pairs
        self.weights = SCORING_WEIGHTS
        self.beta_thresholds = BETA_COEFFICIENT_THRESHOLDS
        logger.info(f"Initialized scanner with {len(self.symbols)} symbols")

    def fetch_ohlcv(self, symbol: str, timeframe: str = '1m', limit: int = 100) -> List:
        """Fetch OHLCV data for a symbol."""
        try:
            data = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            return data
        except Exception as e:
            logger.error(f"Failed to fetch OHLCV for {symbol}: {e}")
            return []

    def calculate_z_score(self, prices: List[float]) -> float:
        """Calculate z-score for price series."""
        if len(prices) < 2:
            return 0.0
        mean = sum(prices) / len(prices)
        variance = sum((x - mean) ** 2 for x in prices) / len(prices)
        std_dev = variance ** 0.5
        if std_dev == 0:
            return 0.0
        return (prices[-1] - mean) / std_dev

    def calculate_relative_strength(self, prices: List[float], benchmark_prices: List[float]) -> float:
        """Calculate relative strength vs benchmark (BTC)."""
        if not benchmark_prices or len(prices) != len(benchmark_prices):
            return 0.0
        try:
            asset_return = (prices[-1] - prices[0]) / prices[0]
            bench_return = (benchmark_prices[-1] - benchmark_prices[0]) / benchmark_prices[0]
            return asset_return - bench_return
        except ZeroDivisionError:
            return 0.0

    def calculate_absorption(self, volume: List[float], price_change: float) -> float:
        """Calculate absorption ratio."""
        if not volume or price_change == 0:
            return 0.0
        avg_volume = sum(volume) / len(volume)
        return avg_volume / abs(price_change) if price_change != 0 else 0.0

    def calculate_squeeze(self, bollinger_width: float, keltner_width: float) -> float:
        """Calculate squeeze indicator."""
        if keltner_width == 0:
            return 0.0
        return 1 - (bollinger_width / keltner_width)

    def calculate_beta_coefficient(self, prices: List[float], btc_prices: List[float]) -> float:
        """Calculate beta coefficient vs BTC."""
        if len(prices) != len(btc_prices) or len(prices) < 2:
            return 1.0
        asset_returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
        btc_returns = [(btc_prices[i] - btc_prices[i-1]) / btc_prices[i-1] for i in range(1, len(btc_prices))]
        covariance = sum((a - sum(asset_returns)/len(asset_returns)) * (b - sum(btc_returns)/len(btc_returns)) for a, b in zip(asset_returns, btc_returns))
        variance = sum((b - sum(btc_returns)/len(btc_returns)) ** 2 for b in btc_returns)
        return covariance / variance if variance != 0 else 1.0

    def check_decoupling(self, beta: float) -> str:
        """Check if asset is decoupling from BTC."""
        if beta > self.beta_thresholds['decoupling_high']:
            return 'strong_decoupling'
        elif beta < self.beta_thresholds['decoupling_low']:
            return 'strong_coupling'
        elif beta > self.beta_thresholds['neutral_high']:
            return 'weak_decoupling'
        elif beta < self.beta_thresholds['neutral_low']:
            return 'weak_coupling'
        else:
            return 'neutral'

    def scan_symbol(self, symbol: str) -> Dict:
        """Scan a single symbol and return scores."""
        ohlcv = self.fetch_ohlcv(symbol)
        if not ohlcv:
            return {'symbol': symbol, 'error': 'No data'}

        prices = [candle[4] for candle in ohlcv]  # Close prices
        volumes = [candle[5] for candle in ohlcv]  # Volumes

        # Fetch BTC data for relative strength and beta
        btc_symbol = 'BTCUSDT'
        btc_ohlcv = self.fetch_ohlcv(btc_symbol) if symbol != btc_symbol else ohlcv
        btc_prices = [candle[4] for candle in btc_ohlcv] if btc_ohlcv else prices

        # Calculate indicators
        z_score = self.calculate_z_score(prices)
        rel_strength = self.calculate_relative_strength(prices, btc_prices)
        absorption = self.calculate_absorption(volumes, prices[-1] - prices[0])
        squeeze = self.calculate_squeeze(0.1, 0.05)  # Placeholder calculations
        beta = self.calculate_beta_coefficient(prices, btc_prices)
        decoupling = self.check_decoupling(beta)

        # Calculate weighted score
        score = (
            self.weights['z_score'] * abs(z_score) +
            self.weights['relative_strength'] * rel_strength +
            self.weights['absorption'] * absorption +
            self.weights['squeeze'] * squeeze
        )

        return {
            'symbol': symbol,
            'z_score': z_score,
            'relative_strength': rel_strength,
            'absorption': absorption,
            'squeeze': squeeze,
            'beta': beta,
            'decoupling': decoupling,
            'total_score': score
        }

    def run_scan(self) -> List[Dict]:
        """Run scan on all symbols."""
        results = []
        for symbol in self.symbols[:10]:  # Limit for demo
            result = self.scan_symbol(symbol)
            results.append(result)
            logger.info(f"Scanned {symbol}: score {result.get('total_score', 'N/A')}")
            time.sleep(0.1)  # Rate limit
        return results

if __name__ == '__main__':
    scanner = CryptoScanner()
    results = scanner.run_scan()
    for result in sorted(results, key=lambda x: x.get('total_score', 0), reverse=True):
        print(f"{result['symbol']}: {result.get('total_score', 'N/A'):.4f} ({result.get('decoupling', 'N/A')})")