import sqlite3
import os
from config import load_config

def migrate():
    cfg = load_config()
    db_path = cfg.db_url.replace("sqlite:///", "")
    
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if mandatory_channels table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mandatory_channels'")
    table_exists = cursor.fetchone()
    
    if not table_exists:
        print("Creating mandatory_channels table...")
        cursor.execute("""
            CREATE TABLE mandatory_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id BIGINT UNIQUE,
                channel_username VARCHAR(100),
                channel_title VARCHAR(200),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        print("✅ Migration completed successfully!")
    else:
        print("ℹ️ mandatory_channels table already exists.")
    
    conn.close()

if __name__ == "__main__":
    migrate()
