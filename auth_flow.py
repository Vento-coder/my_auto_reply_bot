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

    async def send_code(self, tg_user_id: int, phone: str) -> None:
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
