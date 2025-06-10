
#!/usr/bin/env python3
"""
Migration script to add the missing 'network' column to the transaction table
"""

import sqlite3
import os
from datetime import datetime

def migrate_database():
    """Add network column to transaction table if it doesn't exist"""
    
    # Database path
    db_path = os.path.join('instance', 'telegram_signals.db')
    
    if not os.path.exists(db_path):
        print("Database file not found. Creating new database...")
        return
    
    print(f"Migrating database: {db_path}")
    
    try:
        # Connect to database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if network column exists
        cursor.execute("PRAGMA table_info(transaction)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'network' not in columns:
            print("Adding 'network' column to transaction table...")
            cursor.execute("""
                ALTER TABLE "transaction" 
                ADD COLUMN network VARCHAR(32)
            """)
            conn.commit()
            print("✅ Successfully added 'network' column")
        else:
            print("✅ 'network' column already exists")
        
        # Verify the column was added
        cursor.execute("PRAGMA table_info(transaction)")
        columns_after = [column[1] for column in cursor.fetchall()]
        print(f"Transaction table columns: {', '.join(columns_after)}")
        
        conn.close()
        print("✅ Migration completed successfully")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        raise

if __name__ == "__main__":
    print("=" * 50)
    print("Database Migration: Add Network Column")
    print("=" * 50)
    migrate_database()
