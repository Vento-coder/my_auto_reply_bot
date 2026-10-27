import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    bot_token: str
    encryption_key: bytes
    db_url: str
    owner_id: int

def load_config() -> Config:
    return Config(
        api_id=int(os.environ["API_ID"]),
        api_hash=os.environ["API_HASH"],
        bot_token=os.environ["BOT_TOKEN"],
        encryption_key=os.environ["ENCRYPTION_KEY"].encode(),
        db_url=os.environ.get("DB_URL", "sqlite:///userbot.db"),
        owner_id=int(os.environ["OWNER_ID"]),
    )
