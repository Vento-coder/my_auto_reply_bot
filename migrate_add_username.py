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
    
    # Check if username column exists
    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if "username" not in columns:
        print("Adding username column to users table...")
        cursor.execute("ALTER TABLE users ADD COLUMN username VARCHAR(50)")
        conn.commit()
        print("✅ Migration completed successfully!")
    else:
        print("ℹ️ username column already exists.")
    
    conn.close()

if __name__ == "__main__":
    migrate()
