class CategoryNotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("Category not found.")


class CategorySlugConflictError(Exception):
    def __init__(self) -> None:
        super().__init__("Category slug is already in use.")
