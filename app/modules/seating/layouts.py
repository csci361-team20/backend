"""The predefined venue layout(s) shipped with the MVP (SRS 4.3.1).

Ids are derived from names (uuid5), so every environment gets the same ids
and seeding twice changes nothing.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.seating.models import Seat, SeatRow, Venue, VenueSection

_NAMESPACE = uuid.UUID("8c9d1f6e-2b1a-4e0b-9a54-6f1d2a3b4c5d")


def _id(*parts: object) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, "/".join(str(p) for p in parts))


@dataclass(frozen=True)
class RowSpec:
    label: str
    seats: int
    category: str
    accessible: tuple[int, ...] = ()


@dataclass(frozen=True)
class SectionSpec:
    name: str
    rows: tuple[RowSpec, ...]


@dataclass(frozen=True)
class LayoutSpec:
    key: str
    name: str
    address: str
    city: str
    sections: tuple[SectionSpec, ...]


# 136 seats: front stalls (A), rear stalls (B), balcony (C). Wheelchair
# places sit at the ends of the last stalls row, next to the exits.
BILETFLOW_HALL = LayoutSpec(
    key="biletflow-hall",
    name="BiletFlow Hall",
    address="Abay Avenue 1",
    city="Almaty",
    sections=(
        SectionSpec(
            "Stalls",
            tuple(RowSpec(label, 12, "A") for label in "ABC")
            + tuple(RowSpec(label, 12, "B") for label in "DEFG")
            + (RowSpec("H", 12, "B", accessible=(1, 2, 11, 12)),),
        ),
        SectionSpec(
            "Balcony",
            tuple(RowSpec(str(n), 10, "C") for n in range(1, 5)),
        ),
    ),
)

LAYOUTS = (BILETFLOW_HALL,)


def venue_id(spec: LayoutSpec) -> uuid.UUID:
    return _id(spec.key)


async def ensure_predefined_layouts(db: AsyncSession) -> None:
    """Insert the shipped layouts if missing. Safe to call any time."""
    for spec in LAYOUTS:
        vid = venue_id(spec)
        await db.execute(
            insert(Venue)
            .values(id=vid, name=spec.name, address=spec.address, city=spec.city)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        for s_pos, section in enumerate(spec.sections):
            sid = _id(spec.key, section.name)
            await db.execute(
                insert(VenueSection)
                .values(id=sid, venue_id=vid, name=section.name, position=s_pos)
                .on_conflict_do_nothing(index_elements=["id"])
            )
            for r_pos, row in enumerate(section.rows):
                rid = _id(spec.key, section.name, row.label)
                await db.execute(
                    insert(SeatRow)
                    .values(id=rid, section_id=sid, label=row.label, position=r_pos)
                    .on_conflict_do_nothing(index_elements=["id"])
                )
                await db.execute(
                    insert(Seat)
                    .values(
                        [
                            {
                                "id": _id(spec.key, section.name, row.label, n),
                                "row_id": rid,
                                "number": str(n),
                                "position": n,
                                "category": row.category,
                                "is_accessible": n in row.accessible,
                            }
                            for n in range(1, row.seats + 1)
                        ]
                    )
                    .on_conflict_do_nothing(index_elements=["id"])
                )
    await db.commit()
