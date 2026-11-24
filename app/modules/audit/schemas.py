import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEntryResponse(BaseModel):
    """One timeline entry: timestamp, acting user, action, entity, summary."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    actor_user_id: uuid.UUID | None
    actor_name: str | None
    event_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    description: str
    details: dict[str, Any]
