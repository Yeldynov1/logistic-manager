"""Локальна авторизація: паролі тільки як bcrypt у Streamlit Secrets ([auth_users])."""

import bcrypt
import streamlit as st

import config


def _is_bcrypt_hash(value: str) -> bool:
    return isinstance(value, str) and value.startswith(("$2a$", "$2b$", "$2y$"))


def hash_password(password: str) -> str:
    """Для генерації хеша: python auth.py 'ВашПароль'"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def _auth_users_from_secrets():
    try:
        if hasattr(st, "secrets") and "auth_users" in st.secrets:
            return dict(st.secrets["auth_users"])
    except Exception:
        pass
    return {}


def verify_credentials(username: str, password: str) -> bool:
    if not username or not password:
        return False

    auth_users = _auth_users_from_secrets()
    if username in auth_users:
        stored = str(auth_users[username]).strip()
        if not _is_bcrypt_hash(stored):
            return False
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored.encode("ascii"))
        except (ValueError, TypeError):
            return False

    # Зворотна сумісність: plain-text лише якщо задано в config.USERS (не рекомендовано)
    legacy = getattr(config, "USERS", None) or {}
    if username in legacy:
        return legacy[username] == password
    return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Використання: python auth.py 'ВашПароль'")
        print("Скопіюй вивід у Secrets → [auth_users] → логін = \"<хеш>\"")
        sys.exit(1)
    print(hash_password(sys.argv[1]))
