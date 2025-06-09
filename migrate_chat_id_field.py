
from app import app, db
from sqlalchemy import text

def migrate_chat_id_field():
    """Add telegram_chat_id field to User table"""
    with app.app_context():
        try:
            engine_name = db.engine.name
            
            if engine_name == 'sqlite':
                # SQLite approach
                db.engine.execute(text('ALTER TABLE user ADD COLUMN telegram_chat_id VARCHAR(32);'))
            else:
                # PostgreSQL approach
                db.engine.execute(text('ALTER TABLE user ADD COLUMN telegram_chat_id VARCHAR(32) UNIQUE;'))
            
            print("Chat ID field migration completed successfully!")
            
        except Exception as e:
            print(f"Migration failed: {e}")
            # Field might already exist, that's ok
            pass

if __name__ == '__main__':
    migrate_chat_id_field()
