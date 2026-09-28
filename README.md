# EVE Healthcare Backend

FastAPI service for user authentication, diagnostic centre discovery, test bookings, simulated payments, and payment webhooks.

## Architecture

Client → FastAPI → SQLAlchemy/PostgreSQL. Redis caches the public diagnostic catalogue and brokers Celery jobs. The webhook route stores an idempotent event, then a Celery worker updates payment and booking state with retry handling. FastAPI publishes Swagger UI at `/docs` and OpenAPI at `/openapi.json`.

## Features and stack

Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, Redis, Celery, JWT (HS256), Argon2 password hashes, pytest, and Docker Compose. Payment outcomes are simulated; no payment provider is connected.

## Project structure

```text
app/core/       configuration, database, security, Redis cache, Celery setup
app/models/     normalized SQLAlchemy entities
app/schemas/    request and response schemas
app/api/        API routes and pagination
app/services/   booking transitions and webhook processing
app/tasks/      Celery webhook tasks
app/main.py     FastAPI application
alembic/        database migrations
scripts/seed.py sample catalogue data
tests/          API integration tests
```

## Database schema

```text
User 1 ── * Booking * ── 1 CentreTest * ── 1 Centre
                         │               └── 1 DiagnosticTest
                         └── 1 Payment 1 ── * WebhookEvent
```

CentreTest stores a centre's price for a test, so the same test can cost differently by location. Booking references the offered pair and snapshots its price in `amount`; later catalogue changes do not reprice existing bookings. Database constraints enforce unique email, unique event/provider identifiers, foreign keys, unique centre/test offers, and nonnegative prices.

## Setup

### Local

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Set `DATABASE_URL=sqlite:///./eve.db` for SQLite. Configure `REDIS_URL`, `CELERY_BROKER_URL`, and `CELERY_RESULT_BACKEND` to your Redis connection (they can share one Redis database). Keep credentials in `.env`, which is git-ignored. Then initialize the database and seed sample catalogue data:

```bash
python -m alembic upgrade head
python -m scripts.seed
```

Start the API:

```bash
uvicorn app.main:app --reload
```

In another terminal, start the Celery worker. On Windows, use the `solo` pool:

```bash
python -m celery -A app.core.celery_app:celery_app worker --loglevel=INFO --pool=solo --queues=eve_webhooks
```

The default database is SQLite for quick local development. Set `DATABASE_URL` to PostgreSQL for a local Postgres instance. `JWT_SECRET` must be replaced outside development. `PAYMENT_SUCCESS=true` makes the simulation deterministic; set false to simulate failed payments. `LOG_LEVEL` controls application log verbosity. Request limits are configurable with `AUTH_REQUESTS_PER_MINUTE`, `BOOKING_REQUESTS_PER_MINUTE`, `PAYMENT_REQUESTS_PER_MINUTE`, and `WEBHOOK_REQUESTS_PER_MINUTE`.

### Docker

Copy `.env.example` to `.env`, set a private `JWT_SECRET`, then run:

```bash
docker compose up --build
```

Compose starts the API, PostgreSQL, Redis, and Celery worker. The worker listens only to EVE's `eve_webhooks` queue, so it will not consume another app's default `celery` queue when Redis is shared. The API waits for healthy data services and runs `alembic upgrade head` at startup. Named volumes persist PostgreSQL and Redis data. Seed sample catalogue separately with `docker compose exec backend python -m scripts.seed`. Compose uses its Redis container by default; setting Redis URLs in `.env` lets the services use your Redis Cloud instance instead.

## Migrations and sample data

Run `python -m alembic upgrade head` to apply migrations. Create future revisions with `python -m alembic revision --autogenerate -m "description"`, review generated SQL, then apply with `python -m alembic upgrade head`. Run `python -m scripts.seed` for EVE Diagnostics in Dhanbad and CBC, Lipid Profile, Thyroid Profile, and Blood Sugar sample offerings.

## Authentication

Create an account at `/auth/signup`, then send email/password to `/auth/login`. Use the returned token as `Authorization: Bearer <access_token>`. Passwords are Argon2 hashed. Booking list/detail/cancel and payment endpoints require a valid JWT. Booking queries are scoped to the authenticated user's ID; another user's booking appears as 404.

## API endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/auth/signup` | No | Create a user |
| POST | `/auth/login` | No | Issue JWT |
| POST | `/centres/` | Admin key | Create a centre |
| GET | `/centres/` | No | List centres with tests and prices |
| GET | `/centres/{centre_id}` | No | Centre details |
| POST | `/centres/{centre_id}/tests` | Admin key | Offer a test at a centre with its price |
| POST | `/tests/` | Admin key | Create a diagnostic test |
| GET | `/tests/` | No | Test catalogue |
| POST | `/bookings/` | Yes | Create a pending booking |
| GET | `/bookings/` | Yes | List own bookings |
| GET | `/bookings/{booking_id}` | Yes | Read own booking |
| POST | `/bookings/{booking_id}/cancel` | Yes | Cancel pending booking |
| POST | `/payments/` | Yes | Simulate payment for own booking |
| POST | `/payments/webhook/` | Provider | Queue an idempotent payment event |
| GET | `/health` | No | Liveness check |

Centre, test, and booking list endpoints accept `page` and `page_size` query parameters (defaults: page 1, 20 items; maximum page size: 100). Their response uses `{ "items": [...], "total": 0, "page": 1, "page_size": 20, "pages": 0 }`. Booking totals and results are scoped to the authenticated user.

Catalogue write endpoints require `X-Admin-Key`, configured with `ADMIN_API_KEY`; they return 503 until an admin key is configured. Rotate that key like any other application secret. Creating a catalogue item clears relevant Redis cache keys.

## Example requests

```bash
curl -X POST localhost:8000/auth/signup -H 'Content-Type: application/json' -d '{"name":"John Doe","email":"john@example.com","password":"securepassword"}'
curl -X POST localhost:8000/auth/login -H 'Content-Type: application/json' -d '{"email":"john@example.com","password":"securepassword"}'
curl localhost:8000/centres/
curl -X POST localhost:8000/centres/ -H 'X-Admin-Key: YOUR_ADMIN_API_KEY' -H 'Content-Type: application/json' -d '{"name":"EVE Diagnostics","location":"Dhanbad"}'
curl -X POST localhost:8000/tests/ -H 'X-Admin-Key: YOUR_ADMIN_API_KEY' -H 'Content-Type: application/json' -d '{"name":"CBC","description":"Complete blood count"}'
curl -X POST localhost:8000/centres/1/tests -H 'X-Admin-Key: YOUR_ADMIN_API_KEY' -H 'Content-Type: application/json' -d '{"test_id":1,"price":"450.00"}'
curl -X POST localhost:8000/bookings/ -H 'Authorization: Bearer TOKEN' -H 'Content-Type: application/json' -d '{"centre_id":1,"test_id":1,"appointment_datetime":"2026-10-01T10:30:00Z"}'
curl -X POST localhost:8000/payments/ -H 'Authorization: Bearer TOKEN' -H 'Content-Type: application/json' -d '{"booking_id":1}'
curl -X POST localhost:8000/payments/webhook/ -H 'Content-Type: application/json' -d '{"event_id":"evt_123","event_type":"payment.success","payment_id":"PROVIDER_PAYMENT_ID_FROM_PAYMENT_RESPONSE","status":"SUCCESS"}'
```

## Booking and payment rules

```text
PENDING ── payment SUCCESS ──> CONFIRMED
   ├────── payment FAILED ───> FAILED
   └────── cancel ───────────> CANCELLED
```

These are terminal booking states. Failed or cancelled bookings cannot be paid; confirmed bookings cannot be cancelled. Each booking can have one payment attempt. For deterministic evaluation, the simulation immediately sets the payment and booking status using `PAYMENT_SUCCESS`. A delayed event can record the provider's result for a still-pending payment, but cannot reopen a terminal booking; a successful charge after cancellation therefore leaves the booking cancelled and would require a refund workflow in a real integration. A later failure cannot reverse an already successful payment.

Webhook delivery first verifies the payment and stores the event using a unique `event_id`, then dispatches a Celery task. The worker applies payment/booking changes and marks the event processed in one database transaction. Concurrent or repeated deliveries cannot duplicate state changes. A completed event returns `{ "received": true, "duplicate": true, "processing_status": "PROCESSED" }`. Events not yet processed can be re-queued by repeating the same request. Unknown payment IDs return 404 and are not stored.

## Errors

Malformed input receives FastAPI's structured 422 response. Invalid credentials return 401. Missing resources and resources outside the user's scope return 404. Duplicate signup, repeated payment attempts, and invalid state transitions return 409. Invalid centre/test pair or past appointment returns 400. Rate limits return 429. Temporary webhook database failures return 503 with a retry delay. Database errors are not returned to clients.

Sensitive write routes have configurable per-client-IP rate limits. Exceeding a limit returns 429 and a `Retry-After` header. The included limiter stores counters in process memory, which is suitable for local/demo use and a single worker; multi-worker or multi-instance deployments should use a shared store such as Redis.

## Logging and webhook retries

Application events are written as JSON lines with timestamps, severity, event names, and relevant resource IDs. Passwords, tokens, email addresses, and webhook payloads are excluded. Celery retries transient SQLAlchemy failures up to five times with exponential backoff. If the broker is unavailable, the API returns 503 with `Retry-After: 2`; retry the same event ID. Completed events are harmless on redelivery. Invalid payloads and unknown payment IDs return 4xx responses and should not be retried.

Centre and test catalogue responses are cached in Redis for `CACHE_TTL_SECONDS` (default 60). Cache failures are logged and fall back to the database. Catalogue cache keys include page parameters. Catalogue changes made outside the API may remain cached until the TTL expires.

## Tests

```bash
pytest
```

Tests use an isolated in-memory SQLite database and exercise authentication, protected catalogue writes and reads, centre/test offering validation, pagination, booking validation and pricing, ownership, cancellation, successful and failed payments, webhook task processing, idempotency and retry behavior, Redis cache serialization, rate-limit responses, and JSON log formatting.

## Assumptions and limitations

- Appointments are not reserved against an external calendar or slot inventory.
- A booking represents one diagnostic test.
- Prices are captured at booking creation.
- Users can manage only their own bookings.
- Payments are simulations controlled by one environment flag.
- The webhook endpoint models trusted provider delivery; add signature verification before exposing it to a real provider.
- Admin catalogue writes use a shared environment-configured key rather than a full role/permission system. Real payments and notifications are not included.

## Future improvements

Provider signature verification, appointment inventory, role-based admin accounts, notifications, shared rate-limit storage, and log aggregation/tracing could be added as the product requirements grow.
