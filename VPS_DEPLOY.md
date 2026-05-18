# Bybit Scanner VPS Deploy

Target VPS minimum for 100 symbols:

- 2 CPU cores
- 4 GB RAM
- 40 GB NVMe
- Ubuntu 24.04
- 2-4 GB swap

## 1. Install system packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip redis-server git curl ufw
```

## 2. Enable Redis

```bash
sudo systemctl enable redis-server
sudo systemctl start redis-server
redis-cli ping
```

Expected:

```text
PONG
```

## 3. Create app user and directory

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin bybit
sudo mkdir -p /opt/bybit
sudo chown -R bybit:bybit /opt/bybit
```

Copy project files into:

```text
/opt/bybit
```

Do not copy runtime files:

```text
__pycache__/
.ruff_cache/
screenshots/
*.log
app_run.out.log
app_run.err.log
```

## 4. Create virtual environment

```bash
cd /opt/bybit
sudo -u bybit python3 -m venv .venv
sudo -u bybit .venv/bin/pip install --upgrade pip
sudo -u bybit .venv/bin/pip install -r requirements.txt
```

## 5. Configure environment

```bash
sudo cp /opt/bybit/.env.example /opt/bybit/.env
sudo nano /opt/bybit/.env
sudo chown bybit:bybit /opt/bybit/.env
sudo chmod 600 /opt/bybit/.env
```

Fill real values:

```env
BYBIT_API_KEY=
BYBIT_API_SECRET=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
OPENAI_API_KEY=
```

## 6. Configure firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 8000/tcp
sudo ufw enable
```

## 7. Add swap

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 8. Install systemd service

```bash
sudo cp /opt/bybit/deploy/bybit-scanner.service /etc/systemd/system/bybit-scanner.service
sudo systemctl daemon-reload
sudo systemctl enable bybit-scanner
sudo systemctl start bybit-scanner
```

Logs:

```bash
journalctl -u bybit-scanner -f
```

Restart:

```bash
sudo systemctl restart bybit-scanner
```

Stop:

```bash
sudo systemctl stop bybit-scanner
```

## 9. Verify after start

Open:

```text
http://SERVER_IP:8000/
http://SERVER_IP:8000/health-report
http://SERVER_IP:8000/api/health-report
```

CLI checks:

```bash
redis-cli keys "health:heartbeat:*"
redis-cli hgetall system:metrics
redis-cli hgetall realtime:BTCUSDT
curl http://127.0.0.1:8000/api/health-report
```

Healthy target:

```text
overall_status: OK or WARN
configured symbols: 100
fresh realtime symbols: near 100
msgs_per_sec > 0
Streamer: OK
Engine: OK
Redis: OK
```

## 10. Important performance note

With 100 symbols, `loop_latency_ms` can be high on 2 CPU / 4 GB VPS.

Expected ranges:

```text
< 5000 ms      good
5000-10000 ms  acceptable
10000-20000 ms high load
> 20000 ms     optimize or reduce symbols
```

If health report is `WARN` only because of loop latency, the app is running but needs optimization or stronger VPS.
