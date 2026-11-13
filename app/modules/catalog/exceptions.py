class CategoryNotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("Category not found.")
