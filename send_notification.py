#!/usr/bin/env python3
"""
Quick notification sender for testing
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import User, Plan
from telegram_bot import send_subscription_notification

# Send notification to anupx8898 with first available plan
with app.app_context():
    user = User.query.filter_by(telegram_username='anupx8898').first()
    plan = Plan.query.filter_by(is_active=True).first()
    
    if user and plan:
        print(f"Sending notification to @{user.telegram_username} for plan: {plan.name}")
        result = send_subscription_notification(user, plan)
        print(f"Result: {'Success' if result else 'Failed'}")
    else:
        print("User or plan not found")