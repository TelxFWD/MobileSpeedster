#!/usr/bin/env python3
"""
Standalone script to run the Telegram bot
"""
import os
import sys
import logging
from bot_runner import run_bot

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
        sys.exit(1)
    
    logger.info("Starting Telegram bot...")
    run_bot()