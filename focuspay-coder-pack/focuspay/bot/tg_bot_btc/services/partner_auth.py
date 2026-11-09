"""Password hashing for partner accounts (matches exchange auth)."""
import re

import bcrypt

_USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$")


def normalize_username(value: str) -> str:
    return value.strip().lstrip("@").lower()


def validate_username(value: str) -> str:
    u = normalize_username(value)
    if not _USERNAME_RE.match(u):
        raise ValueError("username must be 3-32 chars: a-z, 0-9, underscore")
    return u


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
