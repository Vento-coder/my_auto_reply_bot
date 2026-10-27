import os
from config import load_config
import psycopg2

def migrate():
    cfg = load_config()
    db_url = cfg.db_url
    
    # Parse PostgreSQL URL
    # Format: postgresql://user:password@host:port/database
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://")
    
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from models import Base
    
    engine = create_engine(db_url)
    
    # Check if columns exist
    with engine.connect() as conn:
        result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'approved_by'"))
        columns = [row[0] for row in result]
        
        if 'approved_by' not in columns:
            print("Adding approved_by and approved_at columns...")
            conn.execute(text("ALTER TABLE users ADD COLUMN approved_by BIGINT"))
            conn.execute(text("ALTER TABLE users ADD COLUMN approved_at TIMESTAMP"))
            conn.commit()
            print("✅ Migration completed successfully!")
        else:
            print("ℹ️ Columns already exist.")

if __name__ == "__main__":
    migrate()
