#!/usr/bin/env python3
"""
Test notification system
"""
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import User, Plan, BotSettings
from telegram_bot import send_subscription_notification

def test_notification():
    """Test sending notification to user"""
    with app.app_context():
        # Ensure bot settings are enabled
        bot_settings = BotSettings.query.first()
        if not bot_settings:
            bot_settings = BotSettings(notifications_enabled=True)
            db.session.add(bot_settings)
            db.session.commit()
        else:
            bot_settings.notifications_enabled = True
            db.session.commit()
        
        # Get user and plan
        user = User.query.filter_by(telegram_username='anupx8898').first()
        plan = Plan.query.first()  # Get any plan for testing
        
        if user and plan:
            print(f"Testing notification for user: {user.telegram_username}")
            print(f"Chat ID: {user.telegram_chat_id}")
            print(f"Plan: {plan.name}")
            
            result = send_subscription_notification(user, plan)
            print(f"Notification sent: {result}")
        else:
            print("User or plan not found")
            if not user:
                print("User not found")
            if not plan:
                print("Plan not found")

if __name__ == "__main__":
    test_notification()