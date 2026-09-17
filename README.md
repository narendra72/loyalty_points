# Bean & Balance

A simple café loyalty rewards system built with Flask, SQLite, SQLAlchemy, Jinja2, and Bootstrap 5. Staff can find members by phone, record purchases, redeem points, and view a complete transaction history.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python seed.py
flask --app app run --debug
```

Open `http://127.0.0.1:5000/`. The seed account is `demo` / `demo1234`.

The default database is `loyalty.db` in the Flask instance directory. Set `DATABASE_URL` and `SECRET_KEY` in the environment for a different database and production session key.

## Rewards rules

- Regular earns 1 point per ₹10.
- Silver earns 1.5 points per ₹10, rounded down to a whole point.
- Gold earns 2 points per ₹10.
- Platinum qualifies at 5,000 lifetime earned points and earns 0.3 points per ₹1 spent, rounded down to a whole point.
- Lifetime earned points automatically upgrade a member at 500 points to Silver and at 1,000 points to Gold. Tier upgrades happen after the purchase is earned and are permanent.
- On startup, legacy databases are checked for the `lifetime_points` column and it is backfilled from earn transactions when needed. Existing balances and tiers are preserved; only members already at 5,000+ lifetime points are promoted to Platinum.
- Redemptions decrease only the available balance. A conditional database update prevents the balance from becoming negative, including when two redemptions happen at the same time.
- Every purchase and redemption creates a transaction record in the same database transaction as the balance update.
- Points expire as a full unused balance after more than 90 days without any transaction activity. The expiry job is driven by the persisted simulated clock, not the system clock, and records an `expire` transaction.
- Tier upgrades create a pending notification event in the Outbox table. Outbox records are durable and are created in the same transaction as the tier-changing purchase.

## API

API routes that read or change members require an authenticated session. Call the login endpoint first; Flask's session cookie is then sent with subsequent requests. JSON request bodies are supported for all JSON API endpoints.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/auth/register` | Create a staff account. Body: `username`, `password` (minimum 3 and 8 characters). |
| POST | `/api/auth/login` | Authenticate and start a session. Body: `username`, `password`. |
| GET | `/api/members` | List members. Query: `search`, `page`, `limit` (max 100), `sort` (`name`, `phone`, `tier`, `points`, `created_at`), `order` (`asc` or `desc`). |
| GET | `/api/members/<id>` | Get one member, including balance, tier, and lifetime points. |
| POST | `/api/members` | Create a member. Body: `name`, `phone`; phone numbers are unique. |
| POST | `/api/members/<id>/purchase` | Record a purchase and earn tier-based points. Body: positive `amount`. |
| POST | `/api/members/<id>/redeem` | Redeem points. Body: positive integer `points` and optional positive `amount` for the reward value. |
| GET | `/api/members/<id>/transactions` | List the member's earn and redeem transactions, newest first. |
| POST | `/clock` | Set the simulated current date and run expiry. Body: `{"date": "YYYY-MM-DD"}`. Returns the number of members expired. |
| GET | `/outbox` | List tier-change notification events, newest first. Query: `page` and `limit` (max 100). |

Successful create/purchase/redeem operations return HTTP 201. Validation errors return 400, missing resources return 404, duplicate usernames or phone numbers return 409, and unauthenticated protected requests return 401.

## Project structure

- `app.py`: Flask factory, routes, validation, tier math, and atomic reward operations.
- `models.py`: Member, transaction, staff user, simulated clock, and Outbox models.
- `extensions.py`: SQLAlchemy extension.
- `templates/`: public landing page, auth pages, dashboard, and member detail page.
- `seed.py`: creates demo staff and sample members.
