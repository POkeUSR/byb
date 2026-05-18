import ccxt

# ВСТАВЬ СВОИ КЛЮЧИ
API_KEY = "gjVXIt2S6eVTin0zQn"
SECRET_KEY = "4avDlI1EgvQE7R0gvffQz9vPSq1kiVztIcKd"

# Подключение к Bybit
exchange = ccxt.bybit({
    "apiKey": API_KEY,
    "secret": SECRET_KEY,
    "enableRateLimit": True,
})

try:
    # Проверка подключения
    balance = exchange.fetch_balance()

    print("SUCCESS: API работает")
    print()

    # Печать доступных валют
    for coin, data in balance["total"].items():
        if data and data > 0:
            print(f"{coin}: {data}")

except Exception as e:
    print("ERROR:")
    print(e)