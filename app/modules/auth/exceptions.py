class EmailAlreadyRegisteredError(Exception):
    def __init__(self) -> None:
        super().__init__("A user with this email is already registered.")
