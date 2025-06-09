
from app import app, db
from sqlalchemy import text

def migrate_chat_id_field():
    """Add telegram_chat_id field to User table"""
    with app.app_context():
        try:
            # Check if column already exists
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('user')]
            
            if 'telegram_chat_id' in columns:
                print("telegram_chat_id column already exists!")
                return True
            
            # Add the column
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN telegram_chat_id VARCHAR(32);'))
                conn.commit()
            
            print("Chat ID field migration completed successfully!")
            return True
            
        except Exception as e:
            print(f"Migration failed: {e}")
            return False

if __name__ == '__main__':
    migrate_chat_id_field()
