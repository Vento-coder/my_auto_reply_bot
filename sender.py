from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import AuthKeyUnregisteredError
from config import Config
from crypto import Crypto

class Sender:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.crypto = Crypto(cfg)

    async def send(self, encrypted_session: str, chat_id: int, text: str, reply_to: int = None) -> int:
        session_str = self.crypto.dec(encrypted_session)
        client = TelegramClient(StringSession(session_str), self.cfg.api_id, self.cfg.api_hash)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise AuthKeyUnregisteredError(request=None)
            msg = await client.send_message(chat_id, text, reply_to=reply_to)
            return msg.id
        finally:
            await client.disconnect()
