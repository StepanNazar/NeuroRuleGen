import pickle

import sqlalchemy as sa
from cryptography.fernet import Fernet


class Encrypted(sa.TypeDecorator):
    """A SQLAlchemy type decorator for encrypting and decrypting data using Fernet symmetric encryption."""
    impl = sa.Text
    cache_ok = True

    def __init__(self, encryption_key: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.encryption_key = encryption_key
        self.fernet = Fernet(encryption_key.encode())

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = self.fernet.encrypt(pickle.dumps(value)).decode()
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            value = pickle.loads(self.fernet.decrypt(value.encode()))
        return value

class EncryptedBytes(sa.TypeDecorator):
    """A SQLAlchemy type decorator for encrypting and decrypting bytes using Fernet symmetric encryption."""
    impl = sa.LargeBinary
    cache_ok = True

    def __init__(self, encryption_key: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.encryption_key = encryption_key
        self.fernet = Fernet(encryption_key.encode())

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = self.fernet.encrypt(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            value = self.fernet.decrypt(value)
        return value