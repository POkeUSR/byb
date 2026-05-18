import ccxt

# Подключение к Bybit
exchange = ccxt.bybit()

# Получаем данные FIL/USDT
ticker = exchange.fetch_ticker('FIL/USDT')

# Текущая цена
price = ticker['last']

# Объем за 24 часа
volume = ticker['quoteVolume']

# Изменение цены за 24 часа
change = ticker['percentage']

print(f"FIL PRICE: ${price}")
print(f"24H CHANGE: {change:.2f}%")
print(f"24H VOLUME: ${volume:,.0f}")