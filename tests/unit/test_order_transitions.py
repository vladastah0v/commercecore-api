import pytest

from app.modules.orders.models import OrderStatus
from app.modules.orders.service import ALLOWED_TRANSITIONS


@pytest.mark.parametrize("current", list(OrderStatus))
@pytest.mark.parametrize("target", list(OrderStatus))
def test_allowed_transitions(current: OrderStatus, target: OrderStatus) -> None:
    expected = {
        (OrderStatus.PENDING, OrderStatus.CONFIRMED),
        (OrderStatus.PENDING, OrderStatus.CANCELLED),
        (OrderStatus.CONFIRMED, OrderStatus.COMPLETED),
        (OrderStatus.CONFIRMED, OrderStatus.CANCELLED),
    }
    assert (target in ALLOWED_TRANSITIONS[current]) == ((current, target) in expected)
