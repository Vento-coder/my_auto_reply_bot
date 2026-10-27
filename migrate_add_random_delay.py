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
    
    # Check if random_delay column exists
    cursor.execute("PRAGMA table_info(connected_accounts)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if "random_delay" not in columns:
        print("Adding random_delay column to connected_accounts table...")
        cursor.execute("ALTER TABLE connected_accounts ADD COLUMN random_delay BOOLEAN DEFAULT 0")
        conn.commit()
        print("✅ Migration completed successfully!")
    else:
        print("ℹ️ random_delay column already exists.")
    
    conn.close()

if __name__ == "__main__":
    migrate()
