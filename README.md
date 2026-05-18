# Bybit High-Frequency Crypto Scanner

This project implements a high-frequency crypto scanner for Bybit, using real-time data streaming, storage, analytics, and a web dashboard.

## Files Overview

### config.py
Configuration file containing all settings for the scanner.
- **Symbols**: List of 100 top cryptocurrencies to scan.
- **Redis Settings**: Connection parameters for Redis database.
- **Bybit API**: Credentials for Bybit API (stored in .env).
- **Scoring Weights**: Weights for Z-Score, Relative Strength, Absorption, Squeeze.
- **Beta Coefficients**: Thresholds for BTC decoupling logic.
- **Logging**: Configures professional logging system with file and console output.
- **How it works**: Provides constants and settings used across the application. Imports os for environment variables.

### test_config.py
Unit tests for config.py.
- Tests symbol list length and types.
- Validates scoring weights sum to 1.0 and are floats.
- Checks beta coefficient thresholds structure.
- Verifies Redis and Bybit settings types and ranges.
- Ensures logging configuration is correct.
- **How it works**: Uses unittest to assert configuration validity, ensuring no runtime errors from misconfigurations.

### scanner.py
Main scanner logic using Bybit API and Redis.
- Fetches OHLCV data for symbols.
- Calculates Z-Score, Relative Strength, Absorption, Squeeze indicators.
- Determines decoupling from BTC using beta coefficients.
- Scans all symbols and returns scores.
- **How it works**: Initializes exchange connection, processes each symbol asynchronously, computes indicators using numpy-like logic, stores results.

### history_loader.py
Loads historical data on startup for zero-lag scanning.
- Fetches last 200 minutes of OHLCV data from Bybit.
- Stores prices and volumes in Redis lists (hist:price:{symbol}, hist:vol:{symbol}).
- Uses Pipelines for efficient Redis writes.
- **How it works**: Connects to Bybit, loops through symbols, fetches data with rate limiting, pushes to Redis lists with LTRIM to maintain 200 items.

### test_history_loader.py
Tests for history_loader.py.
- Mocks Bybit API and Redis.
- Verifies data fetching and storage.
- Checks LTRIM maintains list length at 200.
- Tests error handling for failed fetches.
- **How it works**: Uses unittest.mock to simulate external dependencies, asserts correct Redis operations and data integrity.

### storage.py
Asynchronous Redis storage layer.
- update_ticker: Stores price and timestamp in realtime:{symbol} hash.
- update_trades: Atomically updates minute_vol and total_cvd.
- update_orderbook: Stores bid/ask depths.
- update_liquidations: Increments liquidation counter.
- push_history: Appends price/volume to lists with LTRIM.
- get_context: Pipelines fetch of realtime hash and last 200 hist items.
- **How it works**: Uses redis.asyncio for non-blocking operations, employs Pipelines for atomicity and low latency, handles connections gracefully.

### test_storage.py
Stress tests for storage.py.
- Simulates 1000+ trade updates, measures execution time.
- Verifies CVD calculation accuracy.
- Checks historical lists LTRIM to 200 items.
- Tests context retrieval structure.
- **How it works**: Creates concurrent tasks, times operations, asserts data correctness and performance under load.

### data_stream.py
Real-time data streaming from Bybit WebSocket.
- Subscribes to tickers, trades, orderbooks, liquidations for all symbols.
- Processes messages, updates storage with calculated depths.
- Handles reconnections with exponential backoff.
- Sends pings to maintain connection.
- **How it works**: Manages WebSocket connection, parses JSON messages, dispatches to storage update methods, limits to 10 symbols for stability.

### test_stream.py
Integration test for data streaming.
- Runs stream for 60 seconds.
- Retrieves contexts for BTCUSDT and SOLUSDT.
- Checks for populated prices and depths.
- **How it works**: Starts streamer, waits, stops, queries storage, validates live data flow.

### analytics.py
Quantitative analysis engine.
- calculate_z_score: Z-score of volume vs history.
- detect_squeeze: Bollinger width at 100-period min.
- check_absorption: Price flat/falling with rising CVD.
- get_relative_strength: Coin % change vs BTC.
- get_orderbook_imbalance: Bid/ask ratio for pressure.
- **How it works**: Uses numpy/pandas for calculations, handles edge cases like empty data or zero division, provides institutional signals.

### test_analytics.py
Tests for analytics engine.
- Mock data with squeeze, absorption, RS scenarios.
- Verifies correct signal detection.
- **How it works**: Generates synthetic data triggering conditions, runs functions, asserts outputs match expectations.

### web_server.py
FastAPI web server for dashboard.
- Serves index.html at root.
- WebSocket endpoint for real-time client connections.
- Background Redis Pub/Sub listener broadcasts alerts.
- **How it works**: Manages client connections, listens to 'scanner_alerts' channel, pushes messages to WebSockets, uses uvicorn for serving.

### templates/index.html
Dark-themed dashboard UI.
- Tailwind CSS for styling.
- WebSocket connection to server.
- Displays alert cards with score bars, reasoning badges, prices.
- Updates existing alerts, plays beep for high scores.
- View Chart button opens TradingView.
- **How it works**: Parses JSON messages, creates/updates DOM elements, handles user interactions.

### app.py
Main application runner.
- Runs scanner loop every minute.
- Logs top 5 symbols.
- **How it works**: Initializes scanner, enters loop fetching data, analyzing, potentially publishing alerts.

### main.py
Complete system orchestrator for the Bybit Crypto Scanner.
- **Initialization**: Imports all modules, initializes Redis, loads historical data using `history_loader.py`.
- **Background Tasks**: Starts Bybit WebSocket streamer (`BybitDataStream`) for real-time data, and launches FastAPI web server in a separate thread for the dashboard.
- **Main Loop (every 60 seconds)**: Iterates through configured symbols, fetches context from Redis storage, applies wash trading filter (skips if volume / (bid_depth + ask_depth) > 10), calculates Z-score, Squeeze, Absorption, Relative Strength metrics, computes weighted total score, generates alert payload with reasoning tags.
- **Alerting & Publishing**: Publishes all alerts to Redis 'scanner_alerts' channel for web dashboard, sends Telegram notifications for scores >100 by default.
- **Graceful Shutdown**: Handles CTRL+C to cancel tasks and close connections.
- **How it works**: Assembles the entire pipeline - data ingestion via WebSocket, storage in Redis, analytical processing with quant signals, real-time alerting to web UI and Telegram, ensuring low-latency institutional-grade crypto scanning.

### .env
Environment variables.
- Redis and Bybit credentials.
- Logging settings.
- **How it works**: Loaded by config.py for secure credential management.

### requirements.txt
Python dependencies.
- Lists all packages: ccxt, redis, websockets, numpy, pandas, fastapi, uvicorn, etc.
- **How it works**: Used with pip install -r to set up environment.

### README.md
This file - project documentation.

## How to Run
1. Install dependencies: `pip install -r requirements.txt`
2. Set up .env with credentials.
3. Load history: `python history_loader.py`
4. Start web server: `python web_server.py`
5. Run scanner: `python app.py`
6. Open http://localhost:8000 for dashboard.

## Architecture
- **Data Flow**: Bybit WebSocket -> data_stream.py -> storage.py (Redis) -> analytics.py -> scanner.py -> web_server.py -> clients
- **Storage**: Redis for fast access, Pub/Sub for alerts.
- **Analysis**: Numpy/Pandas for efficient computations.
- **UI**: FastAPI + WebSockets for real-time updates.
