import json

from django.db import connection
from django.test import Client, TestCase


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE,
        active INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reward_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT UNIQUE NOT NULL,
        base_points INTEGER NOT NULL,
        multiplier REAL DEFAULT 1,
        max_points INTEGER DEFAULT 100,
        active INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT UNIQUE NOT NULL,
        user_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        amount REAL NOT NULL,
        event_timestamp DATETIME NOT NULL,
        points_awarded INTEGER DEFAULT 0,
        processed INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_points (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE NOT NULL,
        total_points INTEGER DEFAULT 0,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS points_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        points_earned INTEGER NOT NULL,
        description TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        entry_type TEXT DEFAULT 'CREDIT',
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (event_id) REFERENCES events(event_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rewards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reward_code TEXT UNIQUE NOT NULL,
        reward_name TEXT NOT NULL,
        points_required INTEGER NOT NULL,
        active INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS redemptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        redemption_id TEXT UNIQUE NOT NULL,
        user_id INTEGER NOT NULL,
        reward_code TEXT NOT NULL,
        points_spent INTEGER NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (reward_code) REFERENCES rewards(reward_code)
    )
    """,
]


class LoyaltyApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        with connection.cursor() as cursor:
            for statement in SCHEMA:
                cursor.execute(statement)
            for table in [
                "redemptions",
                "points_ledger",
                "events",
                "user_points",
                "rewards",
                "reward_rules",
                "users",
            ]:
                cursor.execute(f"DELETE FROM {table}")

            cursor.execute(
                "INSERT INTO users (id, name, email) VALUES (1, 'Test User', 'test@example.com')"
            )
            cursor.execute(
                """
                INSERT INTO reward_rules
                    (event_type, base_points, multiplier, max_points, active)
                VALUES ('deposit', 10, 1, 100, 1)
                """
            )
            cursor.execute(
                """
                INSERT INTO rewards
                    (reward_code, reward_name, points_required, active)
                VALUES ('coffee', 'Free Coffee', 50, 1)
                """
            )

    def post_json(self, path, payload):
        return self.client.post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_duplicate_event_id_does_not_double_award_points(self):
        payload = {
            "event_id": "evt-test-1",
            "user_id": 1,
            "event_type": "deposit",
            "amount": 100,
            "event_timestamp": "2026-06-20T15:00:00+05:30",
        }

        first = self.post_json("/api/events/", payload)
        duplicate = self.post_json("/api/events/", payload)
        balance = self.client.get("/api/users/1/balance/")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(balance.json()["balance"], 10)

    def test_redemption_fails_when_balance_is_insufficient(self):
        response = self.post_json(
            "/api/redeem/",
            {"user_id": 1, "reward_code": "coffee"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Insufficient points")

    def test_user_active_patch_and_selected_user_balance_ledger(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (id, name, email) VALUES (2, 'Second User', 'second@example.com')"
            )

        patch_response = self.client.patch(
            "/api/users/2/",
            data=json.dumps({"active": 0}),
            content_type="application/json",
        )
        event_response = self.post_json(
            "/api/events/",
            {
                "event_id": "evt-user-2",
                "user_id": 2,
                "event_type": "deposit",
                "amount": 100,
                "event_timestamp": "2026-06-20T15:00:00+05:30",
            },
        )
        balance = self.client.get("/api/balance/?user_id=2")
        ledger = self.client.get("/api/ledger/?customerId=2")

        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.json()["user"]["active"], 0)
        self.assertEqual(event_response.status_code, 201)
        self.assertEqual(balance.json()["user_id"], 2)
        self.assertEqual(balance.json()["balance"], 10)
        self.assertEqual(ledger.json()["user_id"], 2)
        self.assertEqual(len(ledger.json()["ledger"]), 1)

    def test_delete_user_with_history_returns_clear_error(self):
        event_response = self.post_json(
            "/api/events/",
            {
                "event_id": "evt-delete-guard",
                "user_id": 1,
                "event_type": "deposit",
                "amount": 100,
                "event_timestamp": "2026-06-20T15:00:00+05:30",
            },
        )
        delete_response = self.client.delete("/api/users/1/")

        self.assertEqual(event_response.status_code, 201)
        self.assertEqual(delete_response.status_code, 400)
        self.assertEqual(
            delete_response.json()["error"],
            "Cannot delete user because this user has transactions/ledger history. Mark inactive instead.",
        )

    def test_delete_user_without_history_still_works(self):
        create_response = self.post_json(
            "/api/users/",
            {"name": "No History User", "email": "no-history@example.com"},
        )
        user_id = create_response.json()["user"]["id"]
        delete_response = self.client.delete(f"/api/users/{user_id}/")

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(self.client.get(f"/api/users/{user_id}/").status_code, 404)

    def test_event_detail_returns_stored_event_type(self):
        event_response = self.post_json(
            "/api/events/",
            {
                "event_id": "evt-lookup-1",
                "user_id": 1,
                "event_type": "deposit",
                "amount": 100,
                "event_timestamp": "2026-06-20T15:00:00+05:30",
            },
        )
        lookup_response = self.client.get("/api/events/evt-lookup-1/")

        self.assertEqual(event_response.status_code, 201)
        self.assertEqual(lookup_response.status_code, 200)
        self.assertEqual(lookup_response.json()["event"]["event_type"], "deposit")

    def test_reward_create_active_and_inactive(self):
        active = self.post_json(
            "/api/rewards/",
            {
                "reward_code": "tea",
                "reward_name": "Free Tea",
                "points_required": 30,
                "active": 1,
            },
        )
        inactive = self.post_json(
            "/api/rewards/",
            {
                "reward_code": "snack",
                "reward_name": "Free Snack",
                "points_required": 40,
                "active": 0,
            },
        )

        self.assertEqual(active.status_code, 201)
        self.assertEqual(active.json()["reward"]["active"], 1)
        self.assertEqual(inactive.status_code, 201)
        self.assertEqual(inactive.json()["reward"]["active"], 0)

    def test_reward_create_accepts_code_name_aliases(self):
        response = self.post_json(
            "/api/rewards/",
            {
                "code": "cookie",
                "name": "Free Cookie",
                "points_required": 20,
                "active": False,
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["reward"]["reward_code"], "cookie")
        self.assertEqual(response.json()["reward"]["reward_name"], "Free Cookie")
        self.assertEqual(response.json()["reward"]["active"], 0)

    def test_duplicate_active_reward_gives_clear_message(self):
        response = self.post_json(
            "/api/rewards/",
            {
                "reward_code": "coffee",
                "reward_name": "Another Coffee",
                "points_required": 60,
                "active": 1,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Reward code already exists. Use Edit.")

    def test_reward_patch_active_status(self):
        inactive = self.client.patch(
            "/api/rewards/1/",
            data=json.dumps({"active": 0}),
            content_type="application/json",
        )
        active = self.client.patch(
            "/api/rewards/1/",
            data=json.dumps({"active": 1}),
            content_type="application/json",
        )

        self.assertEqual(inactive.status_code, 200)
        self.assertEqual(inactive.json()["reward"]["active"], 0)
        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.json()["reward"]["active"], 1)

    def test_deleted_reward_can_be_created_again(self):
        delete_response = self.client.delete("/api/rewards/1/")
        create_response = self.post_json(
            "/api/rewards/",
            {
                "reward_code": "coffee",
                "reward_name": "Coffee Again",
                "points_required": 55,
                "active": 1,
            },
        )

        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(self.client.get("/api/rewards/1/").status_code, 404)
        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.json()["reward"]["active"], 1)
        self.assertEqual(create_response.json()["reward"]["points_required"], 55)

    def test_reward_rule_create_active_and_inactive(self):
        active = self.post_json(
            "/api/reward-rules/",
            {
                "event_type": "signup",
                "base_points": 25,
                "multiplier": 1,
                "max_points": 25,
                "active": 1,
            },
        )
        inactive = self.post_json(
            "/api/reward-rules/",
            {
                "event_type": "survey",
                "base_points": 5,
                "multiplier": 1,
                "max_points": 5,
                "active": 0,
            },
        )

        self.assertEqual(active.status_code, 201)
        self.assertEqual(active.json()["reward_rule"]["active"], 1)
        self.assertEqual(inactive.status_code, 201)
        self.assertEqual(inactive.json()["reward_rule"]["active"], 0)

    def test_reward_rules_list_includes_event_id_for_dashboard_suggestions(self):
        response = self.client.get("/api/reward-rules/")
        rule = response.json()["reward_rules"][0]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(rule["event_id"], str(rule["id"]))
        self.assertEqual(rule["event_type"], "deposit")

    def test_duplicate_active_reward_rule_gives_clear_message(self):
        response = self.post_json(
            "/api/reward-rules/",
            {
                "event_type": "deposit",
                "base_points": 15,
                "multiplier": 1,
                "max_points": 100,
                "active": 1,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Reward rule already exists. Use Edit.")

    def test_reward_rule_patch_active_status(self):
        inactive = self.client.patch(
            "/api/reward-rules/1/",
            data=json.dumps({"active": 0}),
            content_type="application/json",
        )
        active = self.client.patch(
            "/api/reward-rules/1/",
            data=json.dumps({"active": 1}),
            content_type="application/json",
        )

        self.assertEqual(inactive.status_code, 200)
        self.assertEqual(inactive.json()["reward_rule"]["active"], 0)
        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.json()["reward_rule"]["active"], 1)

    def test_deleted_reward_rule_can_be_created_again(self):
        delete_response = self.client.delete("/api/reward-rules/1/")
        create_response = self.post_json(
            "/api/reward-rules/",
            {
                "event_type": "deposit",
                "base_points": 15,
                "multiplier": 2,
                "max_points": 50,
                "active": 1,
            },
        )

        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(self.client.get("/api/reward-rules/1/").status_code, 404)
        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.json()["reward_rule"]["active"], 1)
        self.assertEqual(create_response.json()["reward_rule"]["base_points"], 15)
