from anyio import to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_password_hasher = PasswordHasher()


async def hash_password(password: str) -> str:
    return await to_thread.run_sync(_password_hasher.hash, password)


async def verify_password(password: str, password_hash: str) -> bool:
    try:
        return await to_thread.run_sync(_password_hasher.verify, password_hash, password)
    except (InvalidHashError, VerificationError):
        return False
