#!/usr/bin/env python3
"""
Migration test script to verify Flask + Telethon integration is working correctly
"""

import os
import sys
import asyncio
import threading
import time
from datetime import datetime

def test_flask_context():
    """Test Flask application context"""
    try:
        from app import app, db
        from sqlalchemy import text
        with app.app_context():
            # Test database connection using SQLAlchemy 2.x syntax
            with db.engine.connect() as connection:
                result = connection.execute(text('SELECT 1'))
                result.fetchone()
            print("✓ Flask application context working")
            print("✓ Database connection successful")
            return True
    except Exception as e:
        print(f"✗ Flask context error: {e}")
        return False

def test_bot_service():
    """Test bot service initialization"""
    try:
        from bot_service import run_bot_service
        print("✓ Bot service module imported successfully")
        
        # Check if bot token is configured
        if os.environ.get('TELEGRAM_BOT_TOKEN'):
            print("✓ Telegram bot token configured")
        else:
            print("⚠ Telegram bot token not configured (standby mode)")
        
        return True
    except Exception as e:
        print(f"✗ Bot service error: {e}")
        return False

def test_enforcement_bot():
    """Test enforcement bot initialization"""
    try:
        from enforcement_bot import EnforcementBot, run_enforcement_bot_background
        print("✓ Enforcement bot module imported successfully")
        
        # Check API credentials
        api_id = os.environ.get('TELEGRAM_API_ID')
        api_hash = os.environ.get('TELEGRAM_API_HASH')
        
        if api_id and api_hash:
            print("✓ Telegram API credentials configured")
        else:
            print("⚠ Telegram API credentials not configured (standby mode)")
        
        return True
    except Exception as e:
        print(f"✗ Enforcement bot error: {e}")
        return False

def test_models():
    """Test database models"""
    try:
        from app import app, db
        from models import User, Admin, Channel, Plan, Subscription
        
        with app.app_context():
            # Test model imports and basic operations
            admin_count = Admin.query.count()
            user_count = User.query.count()
            channel_count = Channel.query.count()
            plan_count = Plan.query.count()
            
            print(f"✓ Database models working - {admin_count} admins, {user_count} users, {channel_count} channels, {plan_count} plans")
            return True
    except Exception as e:
        print(f"✗ Models error: {e}")
        return False

def test_async_integration():
    """Test async/threading integration"""
    try:
        def threaded_test():
            # Create new event loop in thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def async_test():
                await asyncio.sleep(0.1)
                return "async_success"
            
            try:
                result = loop.run_until_complete(async_test())
                return result == "async_success"
            finally:
                loop.close()
        
        # Test in separate thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(threaded_test)
            success = future.result(timeout=5)
        
        if success:
            print("✓ Async/threading integration working")
            return True
        else:
            print("✗ Async/threading integration failed")
            return False
            
    except Exception as e:
        print(f"✗ Async integration error: {e}")
        return False

def main():
    """Run all migration tests"""
    print("Running TeleSignals Migration Tests")
    print("=" * 40)
    print(f"Test started at: {datetime.now()}")
    print()
    
    tests = [
        ("Flask Context", test_flask_context),
        ("Bot Service", test_bot_service),
        ("Enforcement Bot", test_enforcement_bot),
        ("Database Models", test_models),
        ("Async Integration", test_async_integration)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"Testing {test_name}...")
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"✗ {test_name} crashed: {e}")
            results.append((test_name, False))
        print()
    
    # Summary
    print("Migration Test Summary")
    print("=" * 40)
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for test_name, success in results:
        status = "PASS" if success else "FAIL"
        print(f"{test_name}: {status}")
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 Migration completed successfully!")
        print("Your TeleSignals application is ready to use.")
    else:
        print("⚠ Some tests failed. Check the logs above for details.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)