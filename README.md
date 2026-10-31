# Decentro Expense Sharing Service

An async REST API for groups, shared expenses, ledger balances, settlements, and smart settlement suggestions.

## Features

- User and group management with unique group membership.
- Equal expense splits stored as two decimal places; remainder cents go to members in ascending user ID order.
- Group history with payer and participant details and pagination.
- Net balances derived from the expense and settlement ledger.
- Greedy debtor to creditor suggestions that settle all net balances without changing the ledger.
- Optional settlement recording with membership and outstanding debt validation.
- Alembic migrations, PostgreSQL Docker Compose deployment, and isolated SQLite async tests.

## Technology and architecture

Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2 async, PostgreSQL, Alembic, Pytest, and Docker Compose. Routes in `app/api` handle HTTP and validation; `app/services/ledger.py` owns business operations; SQLAlchemy models define persistence; `app/core` holds configuration, database wiring, and consistent application errors.

## Database design

`users` and `groups` are parent entities. `group_members` links them with a unique `(group_id, user_id)`. `expenses` references its group and payer; `expense_splits` stores each participant's share. `settlements` records transfers between group users. Money uses `NUMERIC(12,2)`, timestamps are timezone aware, and indexes support group history and ledger lookups. User references use `RESTRICT` so deleting a user cannot erase ledger history. Deleting a group cascades through its memberships and ledger rows.

```mermaid
erDiagram
    USERS ||--o{ GROUP_MEMBERS : joins
    GROUPS ||--o{ GROUP_MEMBERS : contains
    GROUPS ||--o{ EXPENSES : records
    USERS ||--o{ EXPENSES : pays
    EXPENSES ||--|{ EXPENSE_SPLITS : allocates
    USERS ||--o{ EXPENSE_SPLITS : owes
    GROUPS ||--o{ SETTLEMENTS : records
    USERS ||--o{ SETTLEMENTS : pays_or_receives
```

## API

Swagger UI is at `/docs`; OpenAPI is at `/openapi.json`.

| Method | Path | Description |
|---|---|---|
| POST, GET | `/users` | Create or list users |
| GET | `/users/{user_id}` | Get a user |
| POST, GET | `/groups` | Create or list groups |
| POST, GET | `/groups/{group_id}/members` | Add or list members (`{"user_id": 1}` body for POST; query parameter is also accepted) |
| DELETE | `/groups/{group_id}/members/{user_id}` | Remove a member if no historical ledger row references them |
| POST, GET | `/groups/{group_id}/expenses` | Record an expense or list paginated expense history (`limit`, `offset`) |
| GET | `/expenses/{expense_id}` | Get expense and splits |
| GET | `/groups/{group_id}/balances` | Get net balances and outstanding debts |
| GET | `/groups/{group_id}/settlement-suggestions` | Get suggested transfers |
| POST | `/groups/{group_id}/settlements` | Record a validated settlement |
| GET | `/health` | Liveness check |

Example:

```http
POST /groups/1/expenses
Content-Type: application/json

{"paid_by": 1, "amount": "1200.00", "description": "Dinner", "category": "Food"}
```

An expense response includes `payer_name` and `splits`, each with `user_id`, `user_name`, and `owed_amount`. Balances return `members` with signed `net_balance` values and `debts` with debtor, creditor, and amount. Positive balance means the member is owed money; negative means they owe. The sum is checked to equal zero. A settlement reduces the payer's debt by increasing their net balance and reduces the receiver's credit by decreasing theirs.

Errors use `{"error":{"message":"..."}}` for business errors; Pydantic request errors return FastAPI's standard 422 response.

## Balance and suggestion logic

For an expense, the payer receives credit for the full total and every split participant is debited their split (including the payer's own share). For a settlement, the payer's balance increases by the amount and the recipient's decreases. The API nets these entries by member, then matches the remaining negative balances to positive balances.

Smart suggestions use a greedy debtor-creditor matching pass: repeatedly transfer the smaller of the current debtor's amount and creditor's amount, then advance whichever side is settled. This takes `O(n log n)` to sort by ID for deterministic ordering and `O(n)` matching time, with `O(n)` space. It produces practical direct transfers and minimizes transactions for the straightforward debtor-creditor matching approach; it does not claim global optimality across every possible partition. Suggestions are calculated from a snapshot and do not write settlements.

## Assumptions and decisions

- Every expense is split equally among all current members; the payer also participates in that equal share.
- Amounts accept at most two fractional digits. A split's leftover cents are assigned in stable ascending user ID order.
- Historical expense participants, payers, and settlement parties cannot be removed from the group. This keeps all foreign key and ledger history intact.
- User and group names need not be unique; duplicate membership is a conflict.
- Group deletion and user deletion are not exposed by the API.

## Run locally

Use Python 3.11+, create a virtual environment, install dependencies, and set `DATABASE_URL` to an async PostgreSQL URL:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

For local PostgreSQL, use `postgresql+asyncpg://user:password@localhost:5432/decentro`. Do not commit `.env`.

## Docker

Copy `.env.example` to `.env` if you want to customize configuration, then run:

```sh
docker compose up --build
```

Compose starts PostgreSQL with a persistent named volume and health check. The API waits for database health, applies Alembic migrations at startup, and serves on `http://localhost:8000`. To apply a migration manually: `docker compose exec api alembic upgrade head`.

## Tests

Tests override the database dependency with a fresh in-memory SQLite database per test client, so they do not use production data:

```sh
pytest -q
```

Coverage includes input validation, memberships, equal split rounding, invalid payers and amounts, history pagination, single-member expenses, balances, settlement recording, member removal protection, and smart suggestions.

## Future improvements

- Authentication and authorization for users and groups.
- Currency configuration and localized display formatting.
- Database-level concurrency controls for simultaneous settlements.
- Audit events, idempotency keys, and richer filtering/reporting.
- Property-based tests over randomly generated balanced ledgers.
