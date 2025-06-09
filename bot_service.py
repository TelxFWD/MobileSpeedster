#!/usr/bin/env python3
"""
Bot service that runs alongside the main application
"""
import os
import sys
import threading
import time
import logging
from start_telegram_bot import start_bot

def run_bot_service():
    """Run bot service in a separate thread"""
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    def bot_worker():
        while True:
            try:
                logger.info("Starting Telegram bot service...")
                start_bot()
            except Exception as e:
                logger.error(f"Bot service error: {e}")
                logger.info("Restarting bot service in 5 seconds...")
                time.sleep(5)
    
    # Start bot in background thread
    bot_thread = threading.Thread(target=bot_worker, daemon=True)
    bot_thread.start()
    logger.info("Bot service started in background")

if __name__ == "__main__":
    run_bot_service()
    # Keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Bot service stopped")