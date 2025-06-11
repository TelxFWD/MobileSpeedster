#!/usr/bin/env python3
"""
Migration script to add telegram_channel_id column to channels table
"""

import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

def migrate_telegram_channel_id():
    """Add telegram_channel_id column to Channel table"""
    try:
        # Get database URL
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            print("ERROR: DATABASE_URL not found")
            return False
        
        engine = create_engine(database_url)
        
        with engine.connect() as conn:
            # Check if column already exists
            try:
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'channel' 
                    AND column_name = 'telegram_channel_id'
                """))
                
                if result.fetchone():
                    print("telegram_channel_id column already exists")
                    return True
                    
            except Exception as e:
                print(f"Could not check column existence: {e}")
            
            # Add the column
            try:
                conn.execute(text("""
                    ALTER TABLE channel 
                    ADD COLUMN telegram_channel_id VARCHAR(64)
                """))
                conn.commit()
                print("Successfully added telegram_channel_id column to channel table")
                return True
                
            except OperationalError as e:
                if "already exists" in str(e).lower():
                    print("telegram_channel_id column already exists")
                    return True
                else:
                    print(f"Error adding column: {e}")
                    return False
                    
    except Exception as e:
        print(f"Migration failed: {e}")
        return False

if __name__ == "__main__":
    success = migrate_telegram_channel_id()
    sys.exit(0 if success else 1)