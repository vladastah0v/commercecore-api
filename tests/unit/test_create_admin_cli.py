import getpass

import pytest

from scripts import create_admin


def test_prompt_uses_hidden_password_and_normalizes_input(monkeypatch) -> None:
    monkeypatch.setattr(create_admin.sys.stdin, "isatty", lambda: True)
    answers = iter([" ADMIN@Example.com ", " Admin User "])
    passwords = iter(["secret-password", "secret-password"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr(create_admin.getpass, "getpass", lambda prompt: next(passwords))

    data = create_admin.prompt_admin()

    assert data.email == "admin@example.com"
    assert data.full_name == "Admin User"
    assert data.password.get_secret_value() == "secret-password"
    assert "secret-password" not in repr(data)


def test_noninteractive_input_is_rejected_before_password(monkeypatch) -> None:
    monkeypatch.setattr(create_admin.sys.stdin, "isatty", lambda: False)
    with pytest.raises(RuntimeError, match="interactive terminal"):
        create_admin.prompt_admin()


def test_mismatched_passwords_are_rejected(monkeypatch) -> None:
    monkeypatch.setattr(create_admin.sys.stdin, "isatty", lambda: True)
    answers = iter(["admin@example.com", "Admin"])
    passwords = iter(["first-password", "second-password"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr(create_admin.getpass, "getpass", lambda prompt: next(passwords))
    with pytest.raises(ValueError, match="do not match"):
        create_admin.prompt_admin()


def test_password_is_not_read_when_terminal_cannot_disable_echo(monkeypatch) -> None:
    monkeypatch.setattr(create_admin.sys.stdin, "isatty", lambda: True)
    answers = iter(["admin@example.com", "Admin"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    def insecure_prompt(prompt: str) -> str:
        import warnings

        warnings.warn("Cannot control echo", getpass.GetPassWarning, stacklevel=1)
        raise AssertionError("Password must not be read")

    monkeypatch.setattr(create_admin.getpass, "getpass", insecure_prompt)
    with pytest.raises(getpass.GetPassWarning):
        create_admin.prompt_admin()


def test_invalid_data_does_not_expose_password(monkeypatch, capsys) -> None:
    monkeypatch.setattr(create_admin.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(create_admin.sys, "argv", ["create_admin"])
    answers = iter(["invalid-email", "Admin"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr(create_admin.getpass, "getpass", lambda prompt: "secret-password")
    assert create_admin.main() == 1
    output = capsys.readouterr()
    assert "email" in output.err
    assert "secret-password" not in output.out + output.err
