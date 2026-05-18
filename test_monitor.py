import asyncio
from monitor import SystemMonitor

async def test_monitor():
    monitor = SystemMonitor()

    # Test heartbeat
    await monitor.heartbeat("TestProcess")
    heartbeats = await monitor.get_all_heartbeats()
    assert "TestProcess" in heartbeats

    # Test metrics
    await monitor.set_metric("test", 123)
    metrics = await monitor.get_all_metrics()
    assert metrics.get("test") == "123"

    print("Monitor tests passed")

if __name__ == "__main__":
    asyncio.run(test_monitor())