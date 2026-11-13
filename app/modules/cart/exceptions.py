class CartItemNotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("Cart item not found.")


class CartQuantityLimitError(Exception):
    def __init__(self) -> None:
        super().__init__("Cart item quantity exceeds the allowed limit.")
