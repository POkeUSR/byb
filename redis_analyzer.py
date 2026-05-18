import json
import time
from collections import Counter
from typing import Any, Dict, Iterable, Optional

import redis

import config


BAR_WIDTH = 32


def make_client() -> redis.Redis:
    return redis.Redis(
        host=config.REDIS_HOST,
        port=config.REDIS_PORT,
        db=config.REDIS_DB,
        password=config.REDIS_PASSWORD,
        decode_responses=True,
    )


def as_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
        return number
    except (TypeError, ValueError):
        return None


def bar(value: float, max_value: float, width: int = BAR_WIDTH) -> str:
    if max_value <= 0:
        filled = 0
    else:
        filled = int(min(width, max(0, round((value / max_value) * width))))
    return "#" * filled + "-" * (width - filled)


def human_bytes(value: Optional[int]) -> str:
    if value is None:
        return "n/a"
    units = ["B", "KB", "MB", "GB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f}{unit}"
        size /= 1024
    return f"{size:.2f}GB"


def print_section(title: str) -> None:
    print()
    print("=" * 88)
    print(title)
    print("=" * 88)


def scan_keys(client: redis.Redis) -> list[str]:
    return sorted(client.keys("*"))


def analyze_memory(client: redis.Redis) -> None:
    print_section("REDIS MEMORY")
    info = client.info("memory")
    print(f"target          : {config.REDIS_HOST}:{config.REDIS_PORT}/{config.REDIS_DB}")
    print(f"used_memory     : {info.get('used_memory_human')}")
    print(f"used_peak       : {info.get('used_memory_peak_human')}")
    print(f"dataset         : {human_bytes(info.get('used_memory_dataset'))}")
    print(f"maxmemory       : {info.get('maxmemory_human')}")
    print(f"policy          : {info.get('maxmemory_policy')}")


def analyze_keyspace(client: redis.Redis, keys: list[str]) -> None:
    print_section("KEYSPACE")
    by_type = Counter(client.type(key) for key in keys)
    by_prefix = Counter(key.split(":")[0] for key in keys)

    print(f"total_keys      : {len(keys)}")
    print("by_type         : " + ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())))
    print("by_prefix       :")
    for prefix, count in sorted(by_prefix.items()):
        print(f"  {prefix:<18} {count}")


def analyze_streams(client: redis.Redis) -> None:
    print_section("SIGNAL STREAMS")
    streams = ["signal_analytics", "signal_confirmations"]
    max_len = max([client.xlen(stream) for stream in streams] + [1])

    for stream in streams:
        length = client.xlen(stream)
        memory = client.memory_usage(stream)
        print(f"{stream:<22} len={length:<6} mem={human_bytes(memory):<10} [{bar(length, max_len)}]")

        latest = client.xrevrange(stream, "+", "-", count=1)
        if latest:
            _, fields = latest[0]
            raw = fields.get("data")
            try:
                data = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                data = raw
            print(f"  latest: {data}")


def analyze_symbols(client: redis.Redis) -> None:
    print_section("CURRENT SYMBOLS")
    now_ms = time.time() * 1000
    rows = []

    for symbol in config.SYMBOLS:
        realtime = client.hgetall(f"realtime:{symbol}")
        price_len = client.llen(f"hist:price:{symbol}")
        vol_len = client.llen(f"hist:vol:{symbol}")
        last_update = as_float(realtime.get("last_update"))
        bid = as_float(realtime.get("bid_depth"))
        ask = as_float(realtime.get("ask_depth"))
        cvd = as_float(realtime.get("total_cvd"))
        minute_vol = as_float(realtime.get("minute_vol")) or 0.0
        last_price = as_float(realtime.get("last_price"))

        age = None
        if last_update and last_update > 1_000_000_000_000:
            age = (now_ms - last_update) / 1000

        update_ok = age is not None and age < 30
        depth_ok = bid is not None and ask is not None and (bid + ask) > 0
        cvd_ok = cvd is not None
        history_ok = price_len == 200 and vol_len == 200

        rows.append(
            {
                "symbol": symbol,
                "price": last_price,
                "age": age,
                "minute_vol": minute_vol,
                "depth_ok": depth_ok,
                "cvd_ok": cvd_ok,
                "history_ok": history_ok,
                "price_len": price_len,
                "vol_len": vol_len,
                "status": update_ok and depth_ok and history_ok,
            }
        )

    max_vol = max([row["minute_vol"] for row in rows] + [1])
    header = (
        f"{'SYMBOL':<12} {'PRICE':>14} {'AGE':>8} {'VOL':>12} "
        f"{'DEPTH':>7} {'CVD':>5} {'HIST':>7}  VOLUME"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        price = "n/a" if row["price"] is None else f"{row['price']:.8g}"
        age = "BAD" if row["age"] is None else f"{row['age']:.1f}s"
        depth = "OK" if row["depth_ok"] else "BAD"
        cvd = "OK" if row["cvd_ok"] else "BAD"
        hist = "OK" if row["history_ok"] else f"{row['price_len']}/{row['vol_len']}"
        print(
            f"{row['symbol']:<12} {price:>14} {age:>8} {row['minute_vol']:>12.4f} "
            f"{depth:>7} {cvd:>5} {hist:>7}  [{bar(row['minute_vol'], max_vol, 20)}]"
        )


def analyze_old_keys(client: redis.Redis, keys: Iterable[str]) -> None:
    print_section("NON-CURRENT SYMBOL KEYS")
    current = set(config.SYMBOLS)
    symbol_keys = []
    for key in keys:
        if ":" not in key:
            continue
        prefix, symbol = key.split(":", 1)
        if prefix in {"realtime", "hist"}:
            if prefix == "hist":
                parts = symbol.split(":")
                symbol = parts[-1]
            if symbol not in current:
                symbol_keys.append(key)

    print(f"non_current_keys: {len(symbol_keys)}")
    for key in symbol_keys[:30]:
        print(f"  {key:<35} type={client.type(key):<7} mem={human_bytes(client.memory_usage(key))}")
    if len(symbol_keys) > 30:
        print(f"  ... {len(symbol_keys) - 30} more")


def main() -> None:
    client = make_client()
    if not client.ping():
        raise RuntimeError("Redis ping failed")

    keys = scan_keys(client)
    analyze_memory(client)
    analyze_keyspace(client, keys)
    analyze_streams(client)
    analyze_symbols(client)
    analyze_old_keys(client, keys)


if __name__ == "__main__":
    main()
