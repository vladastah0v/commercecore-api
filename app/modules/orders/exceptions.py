class EmptyCartError(Exception):
    def __init__(self) -> None:
        super().__init__("Cart is empty.")


class OrderProductUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("A product in the cart is unavailable.")


class InsufficientStockError(Exception):
    def __init__(self) -> None:
        super().__init__("Insufficient stock for a product in the cart.")


class IdempotencyConflictError(Exception):
    def __init__(self) -> None:
        super().__init__("Idempotency key was already used for different cart contents.")


class CartChangedError(Exception):
    def __init__(self) -> None:
        super().__init__("Cart contents do not match the checkout request.")


class OrderAmountLimitError(Exception):
    def __init__(self) -> None:
        super().__init__("Order amount exceeds the allowed limit.")
