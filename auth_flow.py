import re
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    PhoneCodeExpiredError, PasswordHashInvalidError
)
from config import Config
from crypto import Crypto

class AuthFlow:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.crypto = Crypto(cfg)
        self._pending: dict[int, dict] = {}

    def normalize_phone(self, phone: str) -> str:
        """Normalize phone number to standard format: +<country_code><number>"""
        # Remove all non-digit characters except + at the start
        phone = phone.strip()
        
        # If starts with +, keep it, otherwise add it
        if not phone.startswith('+'):
            phone = '+' + phone
        
        # Remove all spaces, dashes, dots, parentheses
        phone = re.sub(r'[\s\-\.\(\)]', '', phone)
        
        # Ensure it starts with +
        if not phone.startswith('+'):
            phone = '+' + phone
        
        return phone

    async def send_code(self, tg_user_id: int, phone: str) -> None:
        # Normalize phone number
        phone = self.normalize_phone(phone)
        
        client = TelegramClient(StringSession(), self.cfg.api_id, self.cfg.api_hash)
        await client.connect()
        sent = await client.send_code_request(phone)
        self._pending[tg_user_id] = {"client": client, "phone": phone, "hash": sent.phone_code_hash}

    async def submit_code(self, tg_user_id: int, code: str, password_2fa: str | None = None) -> tuple[str, bool]:
        state = self._pending.get(tg_user_id)
        if not state:
            raise RuntimeError("Avval telefon raqamni yuboring")
        client: TelegramClient = state["client"]

        # Agar 2FA parol kiritilayotgan bo'lsa, kodni qayta yubormaslik kerak
        if password_2fa:
            try:
                await client.sign_in(password=password_2fa)
            except PasswordHashInvalidError:
                raise RuntimeError("2FA parol noto'g'ri")
        else:
            try:
                await client.sign_in(phone=state["phone"], code=code, phone_code_hash=state["hash"])
            except SessionPasswordNeededError:
                return "", False
            except PhoneCodeInvalidError:
                raise RuntimeError("Kod noto'g'ri")
            except PhoneCodeExpiredError:
                raise RuntimeError("Kod muddati o'tgan")

        session_str = client.session.save()
        encrypted = self.crypto.enc(session_str)
        await client.disconnect()
        self._pending.pop(tg_user_id, None)
        return encrypted, True
