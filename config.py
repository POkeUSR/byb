import logging
import os
from dotenv import load_dotenv

load_dotenv()

# Scanner symbols. Keep this list validated against Bybit spot streams.
SYMBOLS = [
    'BTCUSDT',
    'ETHUSDT',
    'SOLUSDT',
    'XRPUSDT',
    'DOGEUSDT',
    'SUIUSDT',
    'PEPEUSDT',
    'FETUSDT',
    'RENDERUSDT',
    'STXUSDT',
    'AAVEUSDT',
    'HYPEUSDT',
    'MNTUSDT',
    'LITUSDT',
    'XAUTUSDT',
    'BTCUSDC',
    'ETHUSDC',
    'ETHBTC',
    'ELSAUSDT',
    'SKRUSDT',
    'SCORUSDT',
    'ENSOUSDT',
    'IPUSDT',
    'ASTERUSDT',
    'MONUSDT',
    'SENTUSDT',
    'FIGHTUSDT',
    'ADAUSDT',
    'BCHUSDT',
    'ZROUSDT',
    'CCUSDT',
    'XPLUSDT',
    'TRXUSDT',
    'LTCUSDT',
    'XRPUSDC',
    'BNBUSDT',
    'LINKUSDT',
    'AVAXUSDT',
    'DOTUSDT',
    'TONUSDT',
    'NEARUSDT',
    'APTUSDT',
    'ARBUSDT',
    'OPUSDT',
    'INJUSDT',
    'SEIUSDT',
    'TIAUSDT',
    'WLDUSDT',
    'FILUSDT',
    'ETCUSDT',
    'ATOMUSDT',
    'ALGOUSDT',
    'VETUSDT',
    'ICPUSDT',
    'GRTUSDT',
    'LDOUSDT',
    'UNIUSDT',
    'RUNEUSDT',
    'KASUSDT',
    'XLMUSDT',
    'JUPUSDT',
    'JTOUSDT',
    'PYTHUSDT',
    'ONDOUSDT',
    'PENDLEUSDT',
    'ENAUSDT',
    'EIGENUSDT',
    'STRKUSDT',
    'ZKUSDT',
    'BLURUSDT',
    'DYDXUSDT',
    'GMXUSDT',
    'WIFUSDT',
    'BONKUSDT',
    'FLOKIUSDT',
    'SHIBUSDT',
    'CRVUSDT',
    'MEMEUSDT',
    'ORDIUSDT',
    'SATSUSDT',
    'SNXUSDT',
    'BOMEUSDT',
    'NOTUSDT',
    'DOGSUSDT',
    'THETAUSDT',
    'MAVIAUSDT',
    'WOOUSDT',
    'PORTALUSDT',
    'JASMYUSDT',
    'GALAUSDT',
    'IMXUSDT',
    'SANDUSDT',
    'MANAUSDT',
    'AXSUSDT',
    'APEUSDT',
    'CHZUSDT',
    'EGLDUSDT',
    'FLOWUSDT',
    'QNTUSDT',
    'ENSUSDT'
]

# Redis Connection Settings
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB = int(os.getenv('REDIS_DB', 0))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)

# Bybit API Placeholders
BYBIT_API_KEY = os.getenv('BYBIT_API_KEY')
BYBIT_API_SECRET = os.getenv('BYBIT_API_SECRET')
BYBIT_TESTNET = os.getenv('BYBIT_TESTNET', 'False').lower() == 'true'

# Scoring Weights
SCORING_WEIGHTS = {
    'z_score': 0.25,
    'relative_strength': 0.25,
    'absorption': 0.25,
    'squeeze': 0.25
}

# Beta Coefficient Thresholds for BTC Decoupling Logic
BETA_COEFFICIENT_THRESHOLDS = {
    'decoupling_high': 1.2,  # Above this, strong decoupling from BTC
    'decoupling_low': 0.8,   # Below this, strong coupling to BTC
    'neutral_high': 1.1,
    'neutral_low': 0.9
}

# Wash Trading Filter Ratio
WASH_TRADING_RATIO = 10.0  # If volume / (bid_depth + ask_depth) > this, skip as potential wash trading

# Telegram Bot Settings (for alerts)
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
TELEGRAM_MIN_SCORE = float(os.getenv('TELEGRAM_MIN_SCORE', 100))

# OpenAI visual chart analysis
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_VISUAL_MODEL = os.getenv('OPENAI_VISUAL_MODEL', 'gpt-4.1-mini')

# Logging Configuration with loguru
from loguru import logger
import sys

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
LOG_FILE = os.getenv('LOG_FILE', 'scanner.log')

# Configure loguru with rotation
logger.remove()  # Remove default handler
logger.add(LOG_FILE, rotation="10 MB", retention="5 days", level=LOG_LEVEL, format="[{time}] [{level}] [{name}] {message}")
logger.add(sys.stdout, level=LOG_LEVEL, format="[{time}] [{level}] [{name}] {message}")

# Module tagging function
def get_logger(module_tag: str):
    return logger.bind(module=module_tag)

# Export main logger
main_logger = logger
