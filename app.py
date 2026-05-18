import time
import logging
from scanner import CryptoScanner
from config import logger

def main():
    scanner = CryptoScanner()
    logger.info("Starting high-frequency crypto scanner")

    while True:
        try:
            results = scanner.run_scan()
            # Here you could save results to Redis or database
            logger.info(f"Scan completed. Top 5 symbols:")
            for result in sorted(results, key=lambda x: x.get('total_score', 0), reverse=True)[:5]:
                logger.info(f"{result['symbol']}: {result.get('total_score', 'N/A'):.4f}")
            time.sleep(60)  # Scan every minute
        except KeyboardInterrupt:
            logger.info("Scanner stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            time.sleep(10)  # Wait before retry

if __name__ == '__main__':
    main()