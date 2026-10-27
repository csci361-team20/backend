import pytest
from pydantic import ValidationError

from app.modules.tickets.schemas import TicketTypeCreate


def test_valid_free_ticket_type():
    ticket_type = TicketTypeCreate(name="General", quantity=100)
    assert ticket_type.price_kzt == 0


def test_negative_price_rejected():
    with pytest.raises(ValidationError):
        TicketTypeCreate(name="VIP", quantity=10, price_kzt=-1)


def test_sale_end_must_be_after_start():
    with pytest.raises(ValidationError):
        TicketTypeCreate(
            name="Early",
            quantity=10,
            sale_start="2026-11-10T10:00:00+05:00",
            sale_end="2026-11-09T10:00:00+05:00",
        )
