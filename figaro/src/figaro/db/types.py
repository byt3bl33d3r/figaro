"""Custom SQLAlchemy column types."""

import os
from typing import Any, Optional

from sqlalchemy import BindParameter, ColumnElement, Text, func, type_coerce
from sqlalchemy.types import LargeBinary, TypeDecorator


class EncryptedString(TypeDecorator[str]):
    """A type that transparently encrypts/decrypts strings using PostgreSQL pgcrypto.

    Uses pgp_sym_encrypt on write and pgp_sym_decrypt on read.
    The encryption key comes from the FIGARO_ENCRYPTION_KEY environment variable.
    """

    impl = LargeBinary
    cache_ok = True

    def bind_expression(self, bindvalue: BindParameter[Any]) -> Optional[ColumnElement[Any]]:  # type: ignore[override]
        key = os.environ.get("FIGARO_ENCRYPTION_KEY", "")
        return func.pgp_sym_encrypt(type_coerce(bindvalue, Text), key)

    def column_expression(self, column: ColumnElement[Any]) -> Optional[ColumnElement[Any]]:
        key = os.environ.get("FIGARO_ENCRYPTION_KEY", "")
        return type_coerce(func.pgp_sym_decrypt(column, key), Text)
