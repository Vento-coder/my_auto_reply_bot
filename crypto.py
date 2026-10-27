from cryptography.fernet import Fernet
from config import Config

class Crypto:
    def __init__(self, cfg: Config):
        self._f = Fernet(cfg.encryption_key)

    def enc(self, s: str) -> str:
        return self._f.encrypt(s.encode()).decode()

    def dec(self, s: str) -> str:
        return self._f.decrypt(s.encode()).decode()
