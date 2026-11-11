import pytest
from pydantic import ValidationError

from app.modules.events.schemas import EventCreate


def _payload(**overrides):
    base = {
        "title": "Concert",
        "start_at": "2026-12-01T18:00:00+05:00",
        "end_at": "2026-12-01T21:00:00+05:00",
        "capacity": 100,
    }
    return {**base, **overrides}


def test_event_create_needs_no_organizer_id():
    assert EventCreate(**_payload()).capacity == 100


def test_end_before_start_rejected():
    with pytest.raises(ValidationError):
        EventCreate(**_payload(end_at="2026-12-01T17:00:00+05:00"))
