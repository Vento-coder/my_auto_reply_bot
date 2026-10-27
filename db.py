from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base
from config import Config
import sqlite3

class DB:
    def __init__(self, cfg: Config):
        # Enable WAL mode and connection pooling for better concurrency
        if cfg.db_url.startswith("sqlite"):
            db_path = cfg.db_url.replace("sqlite:///", "")
            # Enable WAL mode for better concurrency
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.close()
            
            # Create engine with connection pooling
            self.engine = create_engine(
                cfg.db_url,
                future=True,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                connect_args={"timeout": 30}
            )
        else:
            self.engine = create_engine(
                cfg.db_url,
                future=True,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True
            )
        
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def session(self):
        return self.Session()
