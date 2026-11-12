import pytest
from pydantic import ValidationError

from app.modules.events.schemas import EventCreate, EventUpdate


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


def test_event_create_trims_title():
    event = EventCreate(**_payload(title="  Concert  "))
    assert event.title == "Concert"


@pytest.mark.parametrize("title", ["", "   ", "\t\n"])
def test_event_create_rejects_blank_title(title):
    with pytest.raises(ValidationError):
        EventCreate(**_payload(title=title))


def test_event_update_trims_title():
    event = EventUpdate(title="  New Concert  ")
    assert event.title == "New Concert"


@pytest.mark.parametrize("title", ["", "   ", "\t\n"])
def test_event_update_rejects_blank_title(title):
    with pytest.raises(ValidationError):
        EventUpdate(title=title)


def test_event_update_allows_omitted_title():
    update = EventUpdate(capacity=200)
    assert update.title is None
