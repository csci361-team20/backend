# 🏔️ Architecture

This document describes the domain model: roles, core entities, relationships, and the reasoning behind key structural decisions. 



# ❇️ Roles & Permissions

There are two distinct layers of authorization — never model this as a single flat `role` field.

### Global Roles (Stored on `User`)

| Role | Notes |
|---|---|
| `user` (default) | Every registered account. Acts as an Attendee (no separate attendee flag needed). |
| `platform_admin` | Internal platform staff. Boolean or enum on `User`. Grants access to admin endpoints (moderation, activation review, disputes). |

### Event-Scoped Roles (Stored via `StaffAssignment`)

"Organizer" and "Event Admin" are not fixed user types — they are relationships between a `User` and a specific `Event`. A user can be an `OWNER` on one event and `CHECKIN_STAFF` on another at the same time.

| Role (per event) | Capabilities |
|---|---|
| `OWNER` | Created the event. Full control: edit, publish, cancel, activate paid sales, manage staff, manage refunds. |
| `MANAGER` | Organizer-invited co-manager. Same capabilities as `OWNER` minus destructive/financial actions. |
| `CHECKIN_STAFF` | The "Event Admin" role. Mobile app only: scan, verify, and check-in attendees for assigned events. |

> 📌 **Enforcement:** A FastAPI dependency, `require_event_role(event_id, allowed=[...])`, loads the event, checks `StaffAssignment` for `(user_id, event_id)`, and falls back to a `platform_admin` bypass where permitted.



# ❇️ Core Entities

Entities are organized by business module:

- **Identity** — `User`, `OrganizerProfile`, `PayoutAccount`
- **Events & Venue** — `Event`, `Venue`, `VenueSection`, `Row`, `Seat`, `StaffAssignment`
- **Ticketing & Orders** — `TicketType`, `SeatHold`, `Order`, `OrderItem`, `Ticket`, `Payment`, `Refund`
- **Check-in** — `CheckInRecord`
- **Support** — `SupportCase`, `SupportMessage`
- **Promotions** — `PromotionalCampaign`, `PromoCode`, `PromoRedemption`
- **Platform-wide** — `Notification`, `AuditLog` (append-only logs, never editable via API)

### Invariants & Rules

- **QR Tokens:** A `Ticket`'s QR code encodes an opaque, signed token (never the raw database primary key). Verification endpoints look up tokens server-side.
- **Concurrency:** Seat selection and purchase are atomic. Use `SELECT ... FOR UPDATE` on seat rows inside the order transaction to prevent concurrent checkouts on the same seat.
- **Discounts:** Discounts (promo codes, campaign links) are always computed server-side and never trusted from client payloads.
- **State Machine:** `Ticket.status` transitions are strictly one-way, except for explicit, authorized reversals (e.g., undoing a check-in).



# ❇️ Entity Relationship Diagram (ERD)

```mermaid
erDiagram
    USER ||--o| ORGANIZER_PROFILE : "has (optional)"
    USER ||--o{ STAFF_ASSIGNMENT : "assigned to events via"
    USER ||--o{ ORDER : "places"
    USER ||--o{ SUPPORT_CASE : "opens"
    USER ||--o{ SUPPORT_MESSAGE : "sends"
    USER ||--o{ NOTIFICATION : "receives"
    USER ||--o{ AUDIT_LOG : "acts (actor)"

    ORGANIZER_PROFILE ||--o{ EVENT : "owns"
    ORGANIZER_PROFILE ||--o| PAYOUT_ACCOUNT : "has"

    EVENT ||--o{ STAFF_ASSIGNMENT : "has staff"
    EVENT ||--o| VENUE : "held at"
    EVENT ||--o{ TICKET_TYPE : "offers"
    EVENT ||--o{ PROMOTIONAL_CAMPAIGN : "runs"
    EVENT ||--o{ ORDER : "receives"
    EVENT ||--o{ AUDIT_LOG : "logged for"

    VENUE ||--o{ VENUE_SECTION : "contains"
    VENUE_SECTION ||--o{ ROW : "contains"
    ROW ||--o{ SEAT : "contains"
    SEAT ||--o{ SEAT_HOLD : "temporarily held by"
    SEAT ||--o| ORDER_ITEM : "assigned to (if seated)"

    TICKET_TYPE ||--o{ ORDER_ITEM : "purchased as"

    ORDER ||--o{ ORDER_ITEM : "contains"
    ORDER ||--o{ PAYMENT : "paid via"
    ORDER ||--o{ PROMO_REDEMPTION : "may apply"

    ORDER_ITEM ||--o| TICKET : "issues"

    TICKET ||--o{ CHECK_IN_RECORD : "checked in via"

    PAYMENT ||--o{ REFUND : "may be refunded"

    PROMOTIONAL_CAMPAIGN ||--o{ PROMO_CODE : "generates"
    PROMO_CODE ||--o{ PROMO_REDEMPTION : "redeemed as"

    SUPPORT_CASE ||--o{ SUPPORT_MESSAGE : "contains"

    USER {
        uuid id PK
        string email
        string password_hash
        bool is_platform_admin
        datetime email_verified_at
    }

    ORGANIZER_PROFILE {
        uuid id PK
        uuid user_id FK
        string display_name
        string verification_status
    }

    EVENT {
        uuid id PK
        uuid organizer_profile_id FK
        uuid venue_id FK
        string title
        string status
        string visibility
        string seating_type
        datetime start_at
        datetime end_at
        int capacity
        datetime paid_sales_activated_at
    }

    STAFF_ASSIGNMENT {
        uuid id PK
        uuid event_id FK
        uuid user_id FK
        string role "OWNER | MANAGER | CHECKIN_STAFF"
    }

    TICKET_TYPE {
        uuid id PK
        uuid event_id FK
        string name
        int price_kzt
        int quantity
        datetime sale_start
        datetime sale_end
        bool is_hidden
    }

    SEAT {
        uuid id PK
        uuid row_id FK
        string seat_number
        bool is_accessible
        string price_category
    }

    SEAT_HOLD {
        uuid id PK
        uuid seat_id FK
        uuid order_id FK
        datetime expires_at
    }

    ORDER {
        uuid id PK
        uuid user_id FK
        uuid event_id FK
        string status
        int total_kzt
    }

    ORDER_ITEM {
        uuid id PK
        uuid order_id FK
        uuid ticket_type_id FK
        uuid seat_id FK
        int unit_price_kzt
        int quantity
    }

    TICKET {
        uuid id PK
        uuid order_item_id FK
        string attendee_name
        string qr_secret
        string status
    }

    PAYMENT {
        uuid id PK
        uuid order_id FK
        string type
        int amount_kzt
        string status
    }

    REFUND {
        uuid id PK
        uuid payment_id FK
        int amount_kzt
        string status
    }

    CHECK_IN_RECORD {
        uuid id PK
        uuid ticket_id FK
        uuid event_admin_user_id FK
        datetime checked_in_at
        datetime reversed_at
    }

    PROMOTIONAL_CAMPAIGN {
        uuid id PK
        uuid event_id FK
        string discount_type
        int discount_value
        int max_redemptions
    }

    PROMO_CODE {
        uuid id PK
        uuid campaign_id FK
        string code
        bool is_active
    }

    PROMO_REDEMPTION {
        uuid id PK
        uuid promo_code_id FK
        uuid order_id FK
        int discount_amount_kzt
    }

    SUPPORT_CASE {
        uuid id PK
        uuid requester_id FK
        string category
        string status
        uuid assigned_to FK
    }

    SUPPORT_MESSAGE {
        uuid id PK
        uuid case_id FK
        uuid sender_id FK
        string body
    }

    NOTIFICATION {
        uuid id PK
        uuid user_id FK
        string type
        datetime sent_at
    }

    AUDIT_LOG {
        uuid id PK
        uuid actor_id FK
        uuid event_id FK
        string action_type
        string entity_type
    }
```

> 📌 This diagram renders automatically on GitHub. Keep this file as the single source of truth for schema design.



# ❇️ Key Design Decisions

- **Modular Monolith Architecture:** Single deployable application with strict internal boundaries separated into domain folders under `app/modules/`.
- **Two-Layered Role System:** Authorization splits cleanly into global account privileges and per-event staff permissions (see [Roles & Permissions](#roles--permissions)).
- **Native Postgres Concurrency:** Database row locks and unique constraints handle race conditions natively during seat hold and checkout workflows.
- **Dual Database Drivers:** Synchronous `psycopg2` driver for Alembic migration scripts; asynchronous `asyncpg` driver for high-performance API query execution.