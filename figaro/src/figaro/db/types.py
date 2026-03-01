"""Custom SQLAlchemy column types."""

import os

from sqlalchemy import LargeBinary, Text, func, type_coerce
from sqlalchemy.types import TypeDecorator


class EncryptedString(TypeDecorator):
    """A type that transparently encrypts/decrypts strings using PostgreSQL pgcrypto.

    Uses pgp_sym_encrypt on write and pgp_sym_decrypt on read.
    The encryption key comes from the FIGARO_ENCRYPTION_KEY environment variable.
    """

    impl = LargeBinary
    cache_ok = True

    def bind_expression(self, bindvalue):
        key = os.environ.get("FIGARO_ENCRYPTION_KEY", "")
        return func.pgp_sym_encrypt(type_coerce(bindvalue, Text), key)

    def column_expression(self, col):
        key = os.environ.get("FIGARO_ENCRYPTION_KEY", "")
        return type_coerce(func.pgp_sym_decrypt(col, key), Text)
