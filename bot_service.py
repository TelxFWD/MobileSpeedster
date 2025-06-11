#!/usr/bin/env python3
"""
Bot service that runs alongside the main application
"""
import os
import sys
import threading
import time
import logging
import asyncio
from start_telegram_bot import start_bot

def run_bot_service():
    """Run bot service in a separate thread with proper Flask context"""
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    def bot_worker():
        # Check if bot token is available
        if not os.environ.get('TELEGRAM_BOT_TOKEN'):
            logger.info("TELEGRAM_BOT_TOKEN not found. Bot service disabled until token is provided.")
            return
        
        # Import Flask app for context
        try:
            from app import app
        except ImportError as e:
            logger.error(f"Failed to import Flask app: {e}")
            return
            
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run bot within Flask application context
        with app.app_context():
            while True:
                try:
                    logger.info("Starting Telegram bot service...")
                    start_bot()
                except Exception as e:
                    logger.error(f"Bot service error: {e}")
                    logger.info("Restarting bot service in 30 seconds...")
                    time.sleep(30)
    
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