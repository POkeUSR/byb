import asyncio
import json
import websockets
import redis
import numpy as np
from datetime import datetime

# Настройки
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "SUIUSDT", "1000PEPEUSDT"]
WS_URL = "wss://stream.bybit.com/v5/public/linear"

# Подключение к Redis
r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

async def send_ping(ws):
    while True:
        try:
            await asyncio.sleep(20)
            await ws.send(json.dumps({"op": "ping"}))
        except: break

def calculate_z_score(symbol):
    """Считает Z-Score объема на основе истории из Redis"""
    # Получаем последние 100 минутных записей объема
    history = r.lrange(f"hist:vol:{symbol}", 0, 100)
    if len(history) < 20: return 0.0 # Нужно накопить данные
    
    float_history = [float(x) for x in history]
    current_vol = float_history[0]
    past_vol = float_history[1:]
    
    mean = np.mean(past_vol)
    std = np.std(past_vol)
    
    if std == 0: return 0.0
    return (current_vol - mean) / std

async def minute_aggregator():
    """Раз в минуту сохраняет текущий объем в историю для Z-Score"""
    while True:
        await asyncio.sleep(60)
        for symbol in SYMBOLS:
            # Получаем текущий накопленный объем за минуту
            current_min_vol = r.hget(f"realtime:{symbol}", "minute_vol") or 0
            
            # Сохраняем в список (слева)
            r.lpush(f"hist:vol:{symbol}", current_min_vol)
            # Обрезаем список до 200 записей
            r.ltrim(f"hist:vol:{symbol}", 0, 200)
            
            # Сбрасываем счетчик минутной дельты и объема
            r.hset(f"realtime:{symbol}", "minute_vol", 0)
            
            z_score = calculate_z_score(symbol)
            if z_score > 2.0:
                print(f"!!! [ANOMALY] {symbol} Z-Score: {z_score:.2f} !!!")

async def monitor():
    async with websockets.connect(WS_URL) as ws:
        print("CONNECTED. Data streaming to Redis...")
        asyncio.create_task(send_ping(ws))
        asyncio.create_task(minute_aggregator())

        topics = [f"tickers.{s}" for s in SYMBOLS] + [f"publicTrade.{s}" for s in SYMBOLS]
        for i in range(0, len(topics), 10):
            await ws.send(json.dumps({"op": "subscribe", "args": topics[i:i+10]}))

        while True:
            msg = await ws.recv()
            res = json.loads(msg)

            if "topic" in res and "data" in res:
                topic = res["topic"]
                data = res["data"]
                symbol = topic.split('.')[-1]

                if "tickers" in topic:
                    price = data.get("lastPrice")
                    if price:
                        r.hset(f"realtime:{symbol}", "price", price)

                elif "publicTrade" in topic:
                    for trade in data:
                        size = float(trade["v"])
                        side = trade["S"]
                        
                        # Обновляем накопленную дельту и объем в Redis
                        r.hincrbyfloat(f"realtime:{symbol}", "total_cvd", size if side == "Buy" else -size)
                        r.hincrbyfloat(f"realtime:{symbol}", "minute_vol", size)

                # Вывод статуса
                price = r.hget(f"realtime:{symbol}", "price") or "0"
                cvd = r.hget(f"realtime:{symbol}", "total_cvd") or "0"
                print(f"{datetime.now().strftime('%H:%M:%S')} | {symbol:12} | Price: {float(price):10.4f} | CVD: {float(cvd):12.2f}")

if __name__ == "__main__":
    try:
        asyncio.run(monitor())
    except KeyboardInterrupt:
        print("Stopped.")