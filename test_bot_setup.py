#!/usr/bin/env python3
"""
Test script to verify bot setup and database configuration
"""

import os
import sys
from app import app, db
from models import User, Plan, Channel, BotSettings, Subscription
from datetime import datetime, timedelta

def test_bot_setup():
    """Test bot configuration and database setup"""
    with app.app_context():
        print("Testing bot setup...")
        
        # Check bot settings
        bot_settings = BotSettings.query.first()
        if not bot_settings:
            print("Creating bot settings...")
            bot_settings = BotSettings(
                bot_token=os.environ.get('TELEGRAM_BOT_TOKEN'),
                notifications_enabled=True,
                welcome_message='Welcome to TeleSignals!'
            )
            db.session.add(bot_settings)
        else:
            print("Bot settings found, updating...")
            bot_settings.notifications_enabled = True
            if not bot_settings.bot_token:
                bot_settings.bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        
        # Check existing data
        channels = Channel.query.all()
        plans = Plan.query.all()
        users = User.query.all()
        
        print(f"Bot notifications enabled: {bot_settings.notifications_enabled}")
        print(f"Available channels: {len(channels)}")
        print(f"Available plans: {len(plans)}")
        print(f"Total users: {len(users)}")
        
        if channels:
            print("Sample channels:")
            for ch in channels[:3]:
                print(f"  - {ch.name}: {ch.telegram_link}")
        
        if plans:
            print("Sample plans:")
            for plan in plans[:3]:
                plan_channels = plan.get_channels()
                print(f"  - {plan.name}: ${plan.price} for {plan.duration_days} days ({len(plan_channels)} channels)")
        
        # Test user with chat_id
        test_users = User.query.filter(User.telegram_chat_id.isnot(None)).all()
        print(f"Users with chat_id set: {len(test_users)}")
        
        if test_users:
            for user in test_users[:3]:
                print(f"  - @{user.telegram_username}: chat_id={user.telegram_chat_id}")
        
        db.session.commit()
        print("Database updated successfully")
        
        return True

def test_notification_system():
    """Test the notification system"""
    with app.app_context():
        print("\nTesting notification system...")
        
        from telegram_bot import send_subscription_notification, get_user_chat_id
        
        # Find a user and plan for testing
        user = User.query.first()
        plan = Plan.query.first()
        
        if user and plan:
            print(f"Testing notification for user: @{user.telegram_username}")
            print(f"Plan: {plan.name}")
            
            # Check if user has chat_id
            chat_id = get_user_chat_id(user.telegram_username)
            print(f"User chat_id: {chat_id}")
            
            if chat_id:
                print("Attempting to send test notification...")
                result = send_subscription_notification(user, plan)
                print(f"Notification sent: {result}")
            else:
                print("User needs to start the bot to receive notifications")
        else:
            print("No user or plan found for testing")
        
        return True

if __name__ == "__main__":
    test_bot_setup()
    test_notification_system()