class CategoryNotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("Category not found.")


class CategorySlugConflictError(Exception):
    def __init__(self) -> None:
        super().__init__("Category slug is already in use.")


class ProductNotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("Product not found.")


class ProductSlugConflictError(Exception):
    def __init__(self) -> None:
        super().__init__("Product slug is already in use.")
