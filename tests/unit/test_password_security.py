import threading
from unittest.mock import Mock

import pytest

from app.core import security


async def test_hashes_use_unique_salts_and_verify_password() -> None:
    first_hash = await security.hash_password("correct-password")
    second_hash = await security.hash_password("correct-password")

    assert first_hash.startswith("$argon2id$")
    assert first_hash != second_hash
    assert "correct-password" not in first_hash
    assert await security.verify_password("correct-password", first_hash) is True
    assert await security.verify_password("wrong-password", first_hash) is False


@pytest.mark.parametrize("invalid_hash", ["", "not-a-hash", "$argon2id$invalid"])
async def test_invalid_hash_is_rejected(invalid_hash: str) -> None:
    assert await security.verify_password("correct-password", invalid_hash) is False


async def test_password_operations_run_outside_event_loop_thread(monkeypatch) -> None:
    event_loop_thread = threading.get_ident()
    worker_threads: list[int] = []

    def fake_hash(password: str) -> str:
        worker_threads.append(threading.get_ident())
        return "encoded"

    def fake_verify(password_hash: str, password: str) -> bool:
        worker_threads.append(threading.get_ident())
        return True

    hasher = Mock()
    hasher.hash.side_effect = fake_hash
    hasher.verify.side_effect = fake_verify
    monkeypatch.setattr(security, "_password_hasher", hasher)

    assert await security.hash_password("password") == "encoded"
    assert await security.verify_password("password", "encoded") is True
    assert len(worker_threads) == 2
    assert all(thread_id != event_loop_thread for thread_id in worker_threads)
