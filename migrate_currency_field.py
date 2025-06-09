
from app import app, db
from sqlalchemy import text

def migrate_currency_field():
    """Migrate currency field and add network column"""
    with app.app_context():
        try:
            # Check if we're using SQLite or PostgreSQL
            engine_name = db.engine.name
            
            if engine_name == 'sqlite':
                # SQLite approach - create new table and copy data
                db.engine.execute(text('''
                    CREATE TABLE transaction_new (
                        id INTEGER PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        subscription_id INTEGER,
                        transaction_id VARCHAR(128) UNIQUE NOT NULL,
                        payment_method VARCHAR(32) NOT NULL,
                        amount FLOAT NOT NULL,
                        currency VARCHAR(32) NOT NULL,
                        network VARCHAR(32),
                        status VARCHAR(32) NOT NULL,
                        webhook_data TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        completed_at DATETIME,
                        FOREIGN KEY (user_id) REFERENCES user (id),
                        FOREIGN KEY (subscription_id) REFERENCES subscription (id)
                    );
                '''))
                
                # Copy data from old table to new table
                db.engine.execute(text('''
                    INSERT INTO transaction_new (id, user_id, subscription_id, transaction_id, payment_method, amount, currency, status, webhook_data, created_at, completed_at)
                    SELECT id, user_id, subscription_id, transaction_id, payment_method, amount, currency, status, webhook_data, created_at, completed_at FROM transaction;
                '''))
                
                # Drop old table and rename new one
                db.engine.execute(text('DROP TABLE transaction;'))
                db.engine.execute(text('ALTER TABLE transaction_new RENAME TO transaction;'))
                
            else:
                # PostgreSQL approach
                db.engine.execute(text('ALTER TABLE transaction ALTER COLUMN currency TYPE VARCHAR(32);'))
                # Add network column if it doesn't exist
                try:
                    db.engine.execute(text('ALTER TABLE transaction ADD COLUMN network VARCHAR(32);'))
                except:
                    pass  # Column might already exist
            
            print("Migration completed successfully!")
            
        except Exception as e:
            print(f"Migration failed: {e}")
            raise

if __name__ == '__main__':
    migrate_currency_field()
