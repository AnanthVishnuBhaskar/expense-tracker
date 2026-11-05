"""Print a password hash for APP_PASSWORD_HASH:  uv run python -m scripts.hash_password"""

from getpass import getpass

from app.security import hash_password

if __name__ == "__main__":
    password = getpass("New password: ")
    if len(password) < 10:
        raise SystemExit("Use at least 10 characters.")
    if password != getpass("Repeat it: "):
        raise SystemExit("Passwords don't match.")
    print(f"APP_PASSWORD_HASH={hash_password(password)}")
