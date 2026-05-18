import numpy as np
from analytics import AnalyticsEngine

def create_mock_data():
    """Создать mock данные для тестирования"""
    # Prices: 180 normal + 20 tight (squeeze)
    np.random.seed(42)
    normal_prices = 50000 + np.random.uniform(0, 2000, 180)  # Положительные волатильные
    tight_prices = np.full(20, 50000)  # Плоские, для squeeze и absorption
    prices = np.concatenate([normal_prices, tight_prices]).tolist()

    # Volumes for z_score
    volumes = np.random.normal(1000, 200, 200).tolist()

    # CVDs: последние 15 растут, цены плоские
    cvds = list(range(185)) + [185 + i*10 for i in range(15)]  # Растущие последние 15

    # BTC prices: падение -5% за 60 мин
    btc_prices = [50000 * (1 - 0.05 * i / 59) for i in range(60)]

    # Coin prices: рост +5% за 60 мин
    coin_prices = [prices[-60 + i] * (1 + 0.05 * i / 59) for i in range(60)]

    return prices, volumes, cvds, btc_prices, coin_prices

def test_analytics():
    engine = AnalyticsEngine()
    prices, volumes, cvds, btc_prices, coin_prices = create_mock_data()

    # Test Z-score
    z_score = engine.calculate_z_score(volumes)
    print(f"Z-Score: {z_score}")

    # Test Squeeze
    squeeze = engine.detect_squeeze(prices)
    print(f"Squeeze detected: {squeeze}")

    # Test Absorption
    absorption = engine.check_absorption(prices, cvds)
    print(f"Absorption: {absorption}")

    # Test Relative Strength
    rs = engine.get_relative_strength(coin_prices, btc_prices)
    print(f"Relative Strength: {rs}")

    # Test Orderbook Imbalance
    imbalance = engine.get_orderbook_imbalance(10.0, 3.0)  # >2.0
    print(f"Orderbook Imbalance: {imbalance}")

    # Verify
    checks = [
        squeeze == True,  # Should detect squeeze
        absorption == "Bullish",  # Should detect bullish absorption
        rs is not None and rs > 0.05,  # High positive RS
        imbalance == "Strong Buy"
    ]

    if all(checks):
        print("ANALYTICS ENGINE VERIFIED")
    else:
        print("ANALYTICS ENGINE FAILED VERIFICATION")
        print(f"Checks: Squeeze={squeeze}, Absorption={absorption}, RS={rs}, Imbalance={imbalance}")

if __name__ == "__main__":
    test_analytics()