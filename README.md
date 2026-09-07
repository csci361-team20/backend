<h1 align="center">BiletFlow — Backend</h1>

> FastAPI + PostgreSQL backend for BiletFlow, a self-service event and ticket management platform (CSCI361 group project).
>
> This repo is the backend service only. Frontend and mobile live in separate repos in the organization.
>
> **For domain model, roles/permissions, entities, and the ERD, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).<br>For naming/style/branching rules, see [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md).**



# Tech Stack

| Layer | Choice |
|---|---|
| API | FastAPI (async) |
| DB | PostgreSQL, SQLAlchemy 2.0 (async), Alembic migrations |
| Package manager | uv |
| Lint/format | Ruff |
| Tests | Pytest |
| Local infra | Docker Compose |

**How it runs:** both the database and the API live in Docker (`db` + `backend` services). Your code folder is mounted straight into the `backend` container, and it starts with `--reload`, so editing a file on your machine reloads the running server automatically — no rebuild needed for code changes.

# First-Time Setup

1. **Prerequisites** — install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (must be running whenever you work) and [uv](https://docs.astral.sh/uv/) (used for linting/tests on your machine).

2. **Clone & open**
   ```bash
   git clone https://github.com/csci361-team20/backend.git
   cd backend
   code .
   ```

3. **Env file**
   ```bash
   cp .env.example .env
   ```

4. **Install local dependencies** (for Ruff/Pytest/editor autocomplete — separate from the container's own copy)
   ```bash
   uv sync
   ```

5. **Build the images and start everything**
   ```bash
   # If you want to run this in background mode then add flag -d after command
   docker compose up --build
   ```

   This builds the `backend` image (installs Python deps *into* it) and starts both `db` and `backend`.

6. **Build the database tables**
   ```bash
   # This must be run while Docker is working, so to do that - add another terminal and run it there
   docker compose exec backend alembic upgrade head
   ```

✅ Done. Both containers are running, tables exist, dependencies are installed both locally and in the image. You're ready to code.



# Daily Workflow

### 1. Start a branch
```bash
git checkout main
git pull origin main
git checkout -b <your-branch>
```

### 2. Run the ap
```bash
# If you want to run this in background mode then add flag -d after command
docker compose up
```

Starts `db` and `backend` (backend waits until the db is healthy). That's it — one command.

- **Editing Python code?** **Just save** — `--reload` inside the container picks it up instantly. No restart, no rebuild.
- **Added/changed a dependency** in `pyproject.toml`/`uv.lock`, or edited the `Dockerfile`? Rebuild the image:
   ```bash
   # If you want to run this in background mode then add flag -d after command
   docker compose up --build
   ```

- **Check logs:**
  ```bash
  docker compose logs -f backend
  ```
- **Stop everything:**
  ```bash
  docker compose down
  ```
  *Or you can press* `control C` *shortcut to terminate all processes in terminal.*

### 3. Made changes to a model or schema?
**If your change is plain code (no DB), skip this step.**<br>
If your change touches `app/models/` or a module's `models.py`:

1. Edit/add the SQLAlchemy model inside its module (e.g. `app/modules/tickets/models.py`).
2. Import it in `app/models/__init__.py` — Alembic can't autogenerate a table it doesn't see.
3. Generate the migration (this adds model into access scope so Alembic can detect it):
   ```bash
   docker compose exec backend alembic revision --autogenerate -m "add ticket status column"
   ```
4. Apply it (this builds/updates the table with new changes):
   ```bash
   docker compose exec backend alembic upgrade head
   ```

---

*Optional: We can check the existence of tables using `psql`:*

```bash
# Display table's metadata
docker compose exec db psql -U <username> -d <password> -c "\d <table-name>"
# Display table's actual content:
docker compose exec db psql -U <username> -d <password> -c "SELECT * FROM <table-name>;"
```

> 🌭 `<username>` and `<table-name>` are usually in `.env` or `.env.example`, but in our project we use `biletflow` for both of them, so you can just use these commands:

   ```bash
   # Metadata
   docker compose exec db psql -U biletflow -d biletflow -c "\d <table-name>"
   ```

   ```bash
   # Content
   docker compose exec db psql -U biletflow -d biletflow -c "SELECT * FROM <table-name>;"
   ```

> All commands type of `docker compose exec` must be run while docker is running. To do that in parallel, you have to open new terminal and run in there. 

### 4. Quality checks (always, before committing)
These run locally against your `.venv` from `uv sync` — no Docker needed, much faster:
```bash
uv run ruff format .         # auto-format
uv run ruff check . --fix    # lint + auto-fix
uv run ruff check .          # must report "All checks passed!"
uv run pytest                # tests must pass
```

### 5. Commit
```bash
git add .
git commit -m "feat(tickets): add seat-hold expiry logic"
```

### 6. Push & open a PR
```bash
git push origin <your-branch>
```
Open a PR into `main` with a clear description, and wait for CI to pass before merging.



# Project Structure

This backend follows a **Modular Monolith** architecture. Instead of splitting code by technical layers (e.g., all models in one folder, all routes in another), everything belonging to a specific business feature lives together inside `app/modules/<domain>/`.

```text
backend/
├── alembic/                  # Database migration scripts & env configuration
│   └── versions/             # Auto-generated SQL migration files
├── app/
│   ├── api/
│   │   └── v1/
│   │       └── router.py     # Master aggregator: mounts all module routers under /api/v1
│   ├── core/                 # Shared cross-cutting concerns (Global)
│   │   ├── config.py         # App settings & environment variable loader
│   │   └── database.py       # Async SQLAlchemy engine, session maker, & Base model
│   ├── models/
│   │   └── __init__.py       # Re-exports all domain models so Alembic can discover them
│   ├── modules/              # 📦 DOMAIN MODULES (Core Business Logic)
│   │   ├── tickets/          # Tickets domain (models, schemas, service, router)
│   │   └── users/            # Users domain
│   │       ├── models.py     # SQLAlchemy ORM database models
│   │       ├── schemas.py    # Pydantic request & response validation schemas
│   │       ├── service.py    # Business logic & database query operations
│   │       └── router.py     # FastAPI endpoint definitions (/users/...)
│   └── main.py               # Application entrypoint (instantiates FastAPI & middleware)
├── docs/                     # Architecture decisions & coding conventions
├── tests/                    # Pytest suite
├── docker-compose.yml        # Local development environment (DB + API)
├── Dockerfile                # Container build instructions
├── pyproject.toml            # Project dependencies & tool configurations
└── uv.lock                   # Deterministic lockfile for dependencies
```

### What lives where
 
- **`app/modules/<domain>/`** — the actual product features. Each domain is self-contained: everything about `users` (its table, its validation, its logic, its endpoints) lives in one folder. This means you can work on `tickets` without ever opening a `users` file, and merge conflicts between teammates stay rare.
- **`app/api/v1/router.py`** — doesn't contain any logic itself. It just imports each module's `router.py` and mounts it under `/api/v1`, so all endpoints are reachable from one place.
- **`app/core/`** — things every module depends on: DB connection, settings, (later) auth. If two+ modules would need the same helper, it belongs here, not duplicated inside a module.
- **`app/models/__init__.py`** — a registry, not real code. Alembic scans this file to know which tables exist, so any model you write must be imported here or migrations silently ignore it.
- **`app/main.py`** — where the FastAPI app object is created and the v1 router gets attached. You'll rarely touch this after initial setup.
### Anatomy of a module
 
A full module (see `users/` above) has four files, and a request flows through them top to bottom:
 
1. **`router.py`** — defines the HTTP endpoint (`@router.get("/users/{id}")`). Only responsible for: read the request, call `service.py`, return the response. No business logic here.
2. **`schemas.py`** — Pydantic models describing what a valid request/response looks like (e.g. `UserCreate`, `UserOut`). FastAPI uses these to validate input and shape output automatically.
3. **`service.py`** — the actual business logic and DB queries (e.g. "check if email is taken, then insert user"). This is what `router.py` calls into.
4. **`models.py`** — the SQLAlchemy table definition for this domain (e.g. the `User` table).
Keeping these separate means `service.py` can be unit-tested without spinning up HTTP, and the endpoint stays a thin, readable layer.
 
### Adding a new feature
 
- **New endpoint on an existing domain** (e.g. `GET /users/{id}/orders`): add it to that module's `router.py`, add any request/response shape to its `schemas.py`, and put the logic in its `service.py`.
- **New domain entirely** (e.g. `payments`): create `app/modules/payments/` with `router.py`, `schemas.py`, `service.py`, and `models.py` following the `users/` layout, then:
  1. Import its models in `app/models/__init__.py` so Alembic can see them.
  2. Import and mount its router in `app/api/v1/router.py`.
  3. Generate + apply the migration (see the "Made changes to a model or schema?" step in Daily Workflow).
