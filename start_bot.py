#!/usr/bin/env python3
"""
Standalone Telegram Bot Worker
Runs the Telegram bot in polling mode separately from the Flask app
"""

import os
import sys
import logging
import signal
import time
from threading import Event

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import after path setup
from bot_runner import TeleSignalsBot

class BotWorker:
    def __init__(self):
        self.bot = TeleSignalsBot()
        self.shutdown_event = Event()
        self.setup_signal_handlers()
    
    def setup_signal_handlers(self):
        """Setup graceful shutdown handlers"""
        def signal_handler(signum, frame):
            logging.info(f"Received signal {signum}, shutting down...")
            self.shutdown_event.set()
            self.bot.stop_polling()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def run(self):
        """Run the bot worker"""
        logging.info("Starting Telegram Bot Worker...")
        
        if not self.bot.bot:
            logging.error("Failed to initialize bot. Check TELEGRAM_BOT_TOKEN.")
            return 1
        
        try:
            # Start polling in a controlled manner
            while not self.shutdown_event.is_set():
                try:
                    self.bot.start_polling()
                except Exception as e:
                    logging.error(f"Bot polling error: {e}")
                    if not self.shutdown_event.is_set():
                        logging.info("Restarting bot in 5 seconds...")
                        time.sleep(5)
        
        except KeyboardInterrupt:
            logging.info("Received keyboard interrupt")
        
        logging.info("Bot worker shutdown complete")
        return 0

if __name__ == "__main__":
    worker = BotWorker()
    exit_code = worker.run()
    sys.exit(exit_code)