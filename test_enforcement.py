#!/usr/bin/env python3
"""
Test enforcement bot ban functionality
"""

import asyncio
import os
from datetime import datetime, timedelta

def test_enforcement_bot():
    """Test enforcement bot with sample data"""
    from app import app, db
    from models import User, Channel, Plan, Subscription, PlanChannel
    from enforcement_bot import get_enforcement_bot, admin_ban_user, admin_unban_user
    
    with app.app_context():
        # Create test user with expired subscription
        test_user = User(
            telegram_username='testuser',
            telegram_chat_id='123456789',
            pin_hash=generate_password_hash('1234'),
            is_banned=False
        )
        db.session.add(test_user)
        
        # Create test plan
        test_plan = Plan(
            name='Test Plan',
            description='Test plan for enforcement',
            price=10.0,
            duration_days=30,
            is_active=True
        )
        db.session.add(test_plan)
        db.session.flush()  # Get the IDs
        
        # Link plan to existing channel
        channel = Channel.query.first()
        if channel:
            plan_channel = PlanChannel(
                plan_id=test_plan.id,
                channel_id=channel.id
            )
            db.session.add(plan_channel)
        
        # Create expired subscription
        expired_sub = Subscription(
            user_id=test_user.id,
            plan_id=test_plan.id,
            start_date=datetime.utcnow() - timedelta(days=35),
            end_date=datetime.utcnow() - timedelta(days=5),  # Expired 5 days ago
            is_paid=True
        )
        db.session.add(expired_sub)
        
        # Create banned user
        banned_user = User(
            telegram_username='banneduser',
            telegram_chat_id='987654321',
            pin_hash=generate_password_hash('1234'),
            is_banned=True
        )
        db.session.add(banned_user)
        
        db.session.commit()
        
        print("✓ Test data created:")
        print(f"  - User with expired subscription: {test_user.telegram_username}")
        print(f"  - Banned user: {banned_user.telegram_username}")
        print(f"  - Channel: {channel.name if channel else 'None'}")
        print(f"  - Plan: {test_plan.name}")

def test_manual_ban():
    """Test manual ban functionality"""
    print("\nTesting manual ban functionality...")
    
    # Check if enforcement bot is running
    from enforcement_bot import enforcement_bot
    
    if enforcement_bot is None:
        print("✗ Enforcement bot not initialized")
        return False
    
    if not enforcement_bot.client:
        print("✗ Enforcement bot client not connected")
        return False
    
    print("✓ Enforcement bot is running and connected")
    
    # Test manual ban function
    async def test_ban():
        try:
            result = await enforcement_bot.manual_ban_user(123456789, "Test ban")
            print(f"✓ Manual ban result: {result}")
            return True
        except Exception as e:
            print(f"✗ Manual ban failed: {e}")
            return False
    
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Use asyncio.run_coroutine_threadsafe for running loop
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(test_ban(), loop)
            success = future.result(timeout=10)
        else:
            success = loop.run_until_complete(test_ban())
        
        return success
    except Exception as e:
        print(f"✗ Failed to test manual ban: {e}")
        return False

def check_enforcement_status():
    """Check enforcement bot status and configuration"""
    print("\nChecking enforcement bot status...")
    
    # Check environment variables
    api_id = os.environ.get('TELEGRAM_API_ID')
    api_hash = os.environ.get('TELEGRAM_API_HASH')
    bot_mode = os.environ.get('BOT_MODE', 'live')
    
    print(f"API ID configured: {'Yes' if api_id else 'No'}")
    print(f"API Hash configured: {'Yes' if api_hash else 'No'}")
    print(f"Bot mode: {bot_mode}")
    
    from enforcement_bot import enforcement_bot
    
    if enforcement_bot:
        print(f"Bot initialized: Yes")
        print(f"Bot client connected: {'Yes' if enforcement_bot.client else 'No'}")
        print(f"Dry run mode: {enforcement_bot.dry_run}")
        print(f"Max actions per minute: {enforcement_bot.max_actions_per_minute}")
        print(f"Action delay: {enforcement_bot.action_delay} seconds")
    else:
        print("Bot initialized: No")

def main():
    print("Enforcement Bot Test Suite")
    print("=" * 40)
    
    # Check status
    check_enforcement_status()
    
    # Create test data
    test_enforcement_bot()
    
    # Test manual ban (if bot is available)
    test_manual_ban()
    
    print("\nTest completed. Check logs for enforcement bot activity.")

if __name__ == "__main__":
    main()