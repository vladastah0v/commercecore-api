import pytest
from pydantic import ValidationError

from app.modules.auth.schemas import RegisterRequest


def test_valid_registration_is_normalized_and_password_is_masked() -> None:
    request = RegisterRequest(
        email="  USER@Example.COM  ", password=" secure password ", full_name="  Jane Doe  "
    )

    assert request.email == "user@example.com"
    assert request.full_name == "Jane Doe"
    assert request.password.get_secret_value() == " secure password "
    assert " secure password " not in repr(request)
    assert " secure password " not in request.model_dump_json()


@pytest.mark.parametrize("email", ["", "not-an-email", "user@", "@example.com"])
def test_invalid_email_is_rejected(email: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email=email, password="valid-password", full_name="Jane Doe")


@pytest.mark.parametrize("password", ["short", "x" * 129])
def test_password_length_is_validated(password: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="user@example.com", password=password, full_name="Jane Doe")


@pytest.mark.parametrize("length", [8, 128])
def test_password_length_boundaries_are_accepted(length: int) -> None:
    request = RegisterRequest(email="user@example.com", password="x" * length, full_name="Jane Doe")

    assert len(request.password.get_secret_value()) == length


@pytest.mark.parametrize("full_name", ["", "   ", "x" * 256])
def test_full_name_is_not_blank_and_fits_database(full_name: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="user@example.com", password="valid-password", full_name=full_name)


def test_registration_cannot_supply_role() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest.model_validate(
            {
                "email": "user@example.com",
                "password": "valid-password",
                "full_name": "Jane Doe",
                "role": "admin",
            }
        )
