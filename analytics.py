import numpy as np
import pandas as pd
from typing import List, Optional
from config import main_logger

math_logger = main_logger

class AnalyticsEngine:
    def __init__(self):
        pass

    def calculate_z_score(self, volumes: List[float]) -> Optional[float]:
        """Рассчитать Z-score последнего объема относительно истории. Z-score = (текущий - среднее) / std. Это институциональный сигнал волатильности."""
        if len(volumes) < 2:
            return None
        current = volumes[-1]
        history = volumes[:-1]
        mean = np.mean(history)
        std = np.std(history, ddof=1)
        if std == 0:
            z_score = 0.0  # Если нет волатильности, Z-score = 0
        else:
            z_score = (current - mean) / std
        math_logger.debug(f"Z-Score calculated: current={current}, mean={mean:.2f}, std={std:.2f}, z_score={z_score:.2f}")
        return z_score

    def detect_squeeze(self, prices: List[float]) -> bool:
        """Обнаружить сжатие Боллинджера: ширина полос (верхняя - нижняя)/цена на 20 периодах, 2 std. True, если текущая ширина - минимум за 100 периодов. Это сигнал предстоящего движения."""
        if len(prices) < 100:
            squeeze = False
        else:
            df = pd.Series(prices)
            rolling_mean = df.rolling(window=20).mean()
            rolling_std = df.rolling(window=20).std()
            upper = rolling_mean + 2 * rolling_std
            lower = rolling_mean - 2 * rolling_std
            width = (upper - lower) / df
            recent_widths = width.tail(100)
            current_width = recent_widths.iloc[-1]
            squeeze = current_width <= recent_widths.min() + 1e-10
        math_logger.debug(f"Squeeze detected: {squeeze}, current_width={current_width:.6f} if 'current_width' in locals() else 'N/A'")
        return squeeze

    def check_absorption(self, prices: List[float], cvds: List[float]) -> str:
        """Проверить абсорбцию: последние 15 периодов. 'Bullish' если цена плоская или падает, а CVD постоянно растет. Это сигнал накопления."""
        if len(prices) < 15 or len(cvds) < 15:
            absorption = "Neutral"
        else:
            recent_prices = prices[-15:]
            recent_cvds = cvds[-15:]
            price_changes = np.diff(recent_prices)
            price_flat_falling = np.all(price_changes <= 0)
            cvd_rising = np.all(np.diff(recent_cvds) > 0)
            absorption = "Bullish" if price_flat_falling and cvd_rising else "Neutral"
        math_logger.debug(f"Absorption check: {absorption}, price_flat_falling={price_flat_falling if 'price_flat_falling' in locals() else 'N/A'}, cvd_rising={cvd_rising if 'cvd_rising' in locals() else 'N/A'}")
        return absorption

    def get_relative_strength(self, coin_prices: List[float], btc_prices: List[float]) -> Optional[float]:
        """Относительная сила: % изменение монеты vs BTC за последний час (60 мин). Положительное - монета сильнее BTC."""
        if len(coin_prices) < 60 or len(btc_prices) < 60:
            rs = None
        else:
            coin_recent = coin_prices[-60:]
            btc_recent = btc_prices[-60:]
            coin_change = (coin_recent[-1] - coin_recent[0]) / coin_recent[0] if coin_recent[0] != 0 else 0
            btc_change = (btc_recent[-1] - btc_recent[0]) / btc_recent[0] if btc_recent[0] != 0 else 0
            rs = coin_change - btc_change
        math_logger.debug(f"Relative Strength: {rs:.4f} if rs is not None else 'N/A', coin_change={coin_change:.4f} if 'coin_change' in locals() else 'N/A', btc_change={btc_change:.4f} if 'btc_change' in locals() else 'N/A'")
        return rs

    def get_orderbook_imbalance(self, bid_depth: float, ask_depth: float) -> str:
        """Дисбаланс стакана: отношение bid_depth / ask_depth. >2.0 - сильное давление покупок."""
        if ask_depth == 0:
            return "Strong Buy" if bid_depth > 0 else "Neutral"
        ratio = bid_depth / ask_depth
        if ratio > 2.0:
            return "Strong Buy"
        elif ratio < 0.5:
            return "Strong Sell"
        else:
            return "Neutral"

    def analyze_symbol(self, context: dict) -> dict:
        """Анализировать символ на основе контекста из storage."""
        prices = context.get("prices", [])
        volumes = context.get("volumes", [])
        realtime = context.get("realtime", {})
        bid_depth = realtime.get("bid_depth", 0)
        ask_depth = realtime.get("ask_depth", 0)
        # Для CVD, предположим, что cvds - это список, но в контексте нет, так что использовать total_cvd как список из одного
        # Для простоты, check_absorption не используется здесь, или нужно расширить storage
        # Но поскольку функция принимает cvds, в analyze можно не использовать, или добавить позже

        z_score = self.calculate_z_score(volumes)
        squeeze = self.detect_squeeze(prices)
        absorption = self.check_absorption(prices, cvds)
        rs = self.get_relative_strength(prices, [])  # Placeholder, needs btc_prices

        results = {
            "z_score": z_score,
            "squeeze": squeeze,
            "orderbook_imbalance": self.get_orderbook_imbalance(bid_depth, ask_depth),
            # relative_strength требует btc_prices, так что отдельно
            "debug": {
                "raw_values": {
                    "z_score": z_score,
                    "squeeze": squeeze,
                    "absorption": absorption,
                    "relative_strength": rs
                },
                "filter_status": [True, True, True, True],  # Placeholder for filters
                "latency": 0  # To be set in main.py
            }
        }
        return results