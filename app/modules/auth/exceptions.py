class EmailAlreadyRegisteredError(Exception):
    def __init__(self) -> None:
        super().__init__("A user with this email is already registered.")


class InvalidCredentialsError(Exception):
    def __init__(self) -> None:
        super().__init__("Invalid email or password.")


class InvalidRefreshTokenError(Exception):
    def __init__(self) -> None:
        super().__init__("Invalid refresh token.")


class AuthenticationRequiredError(Exception):
    def __init__(self) -> None:
        super().__init__("Invalid or missing authentication credentials.")


class InsufficientPermissionsError(Exception):
    def __init__(self) -> None:
        super().__init__("Insufficient permissions.")
