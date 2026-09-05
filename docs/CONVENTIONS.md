# 📜 Conventions

Naming, style, git branching, and commit conventions for the BiletFlow backend. Ruff enforces code formatting automatically — this guide covers structure, naming, and workflow rules.



# ✳️ Naming Conventions

### Python Code
- `snake_case`: Variables, functions, methods, file names, and directory names.
- `PascalCase`: Classes (SQLAlchemy models, Pydantic schemas, custom exceptions).
- `UPPER_SNAKE_CASE`: Constants (`MAX_SEAT_HOLD_MINUTES = 15`).
- **Private functions/methods:** Use a single leading underscore (`_validate_capacity`, `_hash_password`) for functions internal to a module that should not be imported elsewhere.
- **Booleans:** Name boolean variables as predicate questions: `is_active`, `has_paid`, `can_edit` (never `active_flag` or `status`).
- **Functions:** Always start with an active verb: `create_user()`, `get_event_by_id()`, `cancel_order()`.

### Database Schema
- **Table names:** Plural `snake_case` (`users`, `tickets`, `order_items`).
- **Column names:** Singular `snake_case` without type prefixes (`price_kzt`, not `int_price`).
- **Foreign Keys:** `<singular_target_table>_id` (`user_id`, `event_id`).
- **Booleans:** Same question-form as Python (`is_active`, `is_verified`).

### Pydantic Schemas (`app/modules/<feature>/schemas.py`)
Schemas use explicit action suffixes to differentiate request/response data:

| Purpose | Suffix Pattern | Example | Description |
| :--- | :--- | :--- | :--- |
| **Input (POST)** | `Create` | `UserCreate` | Strict payload for resource creation. |
| **Input (PATCH/PUT)** | `Update` | `UserUpdate` | Payload for updates (all fields optional). |
| **Output (HTTP Response)** | `Response` | `UserResponse` | Public response returned to clients. |
| **Internal / DB** | `InDB` / `Internal` | `UserInDB` | Service-layer data including sensitive attributes (e.g., `hashed_password`). |
| **Query Params** | `Filter` / `Params` | `UserFilter` | Validates search, sorting, and pagination URL parameters. |

> 📌 **Rule:** Never reuse a single schema for both input and output if sensitive, system-generated (`id`, `created_at`), or internal fields differ.



# ✳️ Git Branching Convention

All branch names must follow the format: **`type/short-description`** (lowercase, hyphen-separated).

### Branch Types

| Type | When to Use | Example |
| :--- | :--- | :--- |
| `feat` | A new feature or user story | `feat/users-auth-login` |
| `fix` | A bug fix | `fix/jwt-expiration-check` |
| `refactor` | Code restructuring without feature/bug changes | `refactor/modular-router-wiring` |
| `docs` | Documentation updates | `docs/update-conventions` |
| `chore` | Maintenance, dependencies, tool setup | `chore/update-ruff-config` |
| `test` | Adding or updating tests | `test/user-service-unit-tests` |

### Branching Rules
1. Branch off the latest `main`.
2. Keep branches small and feature-focused.
3. Rebase onto `main` before opening a Pull Request if `main` has moved ahead.
4. Always squash-merge PRs to keep `main` history clean (1 commit per merged PR).
5. Delete feature branches immediately after merging.



# ✳️ Commit Message Convention

Commits must follow the **Conventional Commits** specification in the format:

$$\text{type}(\text{scope}):\text{ change-description}$$

- **Format:** Lowercase, imperative mood ("add", not "added" or "adds").
- **Scope:** The module or component being modified (`users`, `tickets`, `core`, `deps`, `readme`).

### Supported Commit Types

| Type | Description | Example |
| :--- | :--- | :--- |
| `feat` | A new business feature | `feat(users): implement user registration service` |
| `fix` | A bug fix | `fix(auth): fix password verification hash mismatch` |
| `refactor` | Code change that neither fixes a bug nor adds a feature | `refactor(tickets): extract seat locking logic into service` |
| `docs` | Documentation changes only | `docs(readme): update project structure and setup steps` |
| `chore` | Maintenance, config updates, dependency bumps | `chore(deps): update uv.lock dependencies` |
| `test` | Adding missing tests or refactoring existing tests | `test(users): add unit tests for user creation service` |
| `ci` | Continuous integration pipeline changes | `ci(github): add ruff and pytest workflows` |
| `perf` | Performance improvements | `perf(database): add index for event search by date` |




# ✳️ Architecture & Code Style Rules

1. **Modular Monolith Layering:**
   - **`router.py`**: Thin HTTP layer. Validates requests via schemas, calls services, and returns responses. No SQL or business logic here.
   - **`service.py`**: Core business logic and database access.
   - **`models.py`**: Database table schemas using SQLAlchemy ORM.
   - **`schemas.py`**: Pydantic models for serialization and validation.
2. **Error Handling:** Raise domain exceptions in `service.py`. Translate exceptions into `HTTPException` inside `router.py`.
3. **Type Annotations:** Type-hint all function signatures (arguments and return types). Avoid bare `Any`.
4. **Explicit Imports:** Use explicit module imports (`from app.modules.users.models import User`) instead of wildcard imports (`from app.modules.users.models import *`).