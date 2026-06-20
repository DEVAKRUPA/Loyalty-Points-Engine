# Loyalty Points Engine

## Project Overview

A small Django + SQLite loyalty points engine with a browser dashboard and JSON API for managing users, reward rules, rewards, point-earning events, redemptions, balances, ledgers, and event reversals.

The dashboard is available at:

```text
http://127.0.0.1:8000/
```

## Tech Stack

- Python
- Django
- SQLite
- Django templates
- Plain CSS and JavaScript
  
## Local Setup (Windows PowerShell)

```powershell
cd "Loyalty Points Engine"
```

Install dependencies:

```powershell
pip install -r requirements.txt
```
Install dependencies:

```powershell
pip install -r requirements.txt
```

Run migrations only if you are setting up a new database:

```powershell
python manage.py migrate
```

For the included `rewards.db`, migrations are not required because the SQLite tables already exist.

Run the server:

```powershell
python manage.py runserver 127.0.0.1:8000
```

## SQLite Database Note

The project uses `rewards.db` in the project root. The database is configured in `loyalty_project/settings.py`.

The API writes to the existing SQLite tables used by the loyalty engine, including users, reward rules, events, ledger entries, user points, rewards, and redemptions.

## API Endpoints

- `GET /api/users/`
- `POST /api/users/`
- `GET /api/users/<user_id>/`
- `PUT /api/users/<user_id>/`
- `PATCH /api/users/<user_id>/`
- `DELETE /api/users/<user_id>/`
- `GET /api/reward-rules/`
- `POST /api/reward-rules/`
- `GET /api/reward-rules/<rule_id>/`
- `PUT /api/reward-rules/<rule_id>/`
- `PATCH /api/reward-rules/<rule_id>/`
- `DELETE /api/reward-rules/<rule_id>/`
- `GET /api/rewards/`
- `POST /api/rewards/`
- `GET /api/rewards/<reward_id>/`
- `PUT /api/rewards/<reward_id>/`
- `PATCH /api/rewards/<reward_id>/`
- `DELETE /api/rewards/<reward_id>/`
- `POST /api/events/`
- `GET /api/events/<event_id>/`
- `POST /api/events/<event_id>/reverse/`
- `GET /api/balance/?user_id=<user_id>`
- `GET /api/ledger/?user_id=<user_id>`
- `GET /api/users/<user_id>/balance/`
- `GET /api/users/<user_id>/ledger/`
- `POST /api/redeem/`

## API Examples

Create a user:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/users/ -H "Content-Type: application/json" -d '{"name":"Test User","email":"test@example.com"}'
```

List users:

```powershell
curl.exe http://127.0.0.1:8000/api/users/
```

Create a reward rule:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/reward-rules/ -H "Content-Type: application/json" -d '{"event_type":"signup","base_points":25,"multiplier":1,"max_points":25,"active":1}'
```

List reward rules:

```powershell
curl.exe http://127.0.0.1:8000/api/reward-rules/
```

Create a reward:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/rewards/ -H "Content-Type: application/json" -d '{"reward_code":"tea","reward_name":"Free Tea","points_required":30,"active":1}'
```

List rewards:

```powershell
curl.exe http://127.0.0.1:8000/api/rewards/
```

Earn points with an event:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/events/ -H "Content-Type: application/json" -d '{"event_id":"evt-1001","user_id":1,"event_type":"deposit","amount":100,"event_timestamp":"2026-06-20T15:00:00+05:30"}'
```

Idempotency check by sending the same `event_id` twice:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/events/ -H "Content-Type: application/json" -d '{"event_id":"evt-1001","user_id":1,"event_type":"deposit","amount":100,"event_timestamp":"2026-06-20T15:00:00+05:30"}'
curl.exe -X POST http://127.0.0.1:8000/api/events/ -H "Content-Type: application/json" -d '{"event_id":"evt-1001","user_id":1,"event_type":"deposit","amount":100,"event_timestamp":"2026-06-20T15:00:00+05:30"}'
```

The second request returns an already-processed response and does not credit points again.

Redeem a reward:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/redeem/ -H "Content-Type: application/json" -d '{"user_id":1,"reward_code":"tea"}'
```

Insufficient balance redemption example:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/redeem/ -H "Content-Type: application/json" -d '{"user_id":1,"reward_code":"coffee"}'
```

Check balance:

```powershell
curl.exe http://127.0.0.1:8000/api/balance/?user_id=1
```

Ledger:

```powershell
curl.exe http://127.0.0.1:8000/api/ledger/?user_id=1
```

Reverse an event:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/events/evt-1001/reverse/
```

## Behavior Notes

`event_id` is unique in the `events` table. Reposting the same event does not add another ledger credit.

Ledger history is append-only. Balance is calculated from ledger entries and mirrored into `user_points`.

User delete is blocked when the user has transaction or ledger history. Use the Active/Inactive toggle instead.

## Testing

Run the test suite:

```powershell
python manage.py test
```
