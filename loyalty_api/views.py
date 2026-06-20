import json
from functools import wraps
from uuid import uuid4

from django.db import DatabaseError, IntegrityError, connection, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt


def dict_fetchone(cursor):
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [column[0] for column in cursor.description]
    return dict(zip(columns, row))


def dict_fetchall(cursor):
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def read_json(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return None


def require_fields(data, fields):
    missing = [field for field in fields if data.get(field) is None]
    if missing:
        return JsonResponse(
            {"error": f"Missing required field(s): {', '.join(missing)}"},
            status=400,
        )
    return None


def method_not_allowed():
    return JsonResponse({"error": "Method not allowed"}, status=405)


def json_api_errors(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            prepare_database_connection()
            return view_func(request, *args, **kwargs)
        except DatabaseError as exc:
            return JsonResponse(
                {
                    "error": "Database error",
                    "details": str(exc),
                    "path": request.path,
                },
                status=500,
            )

    return wrapper


def prepare_database_connection():
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=MEMORY")


def get_balance(user_id):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COALESCE(SUM(points_earned), 0) AS balance
            FROM points_ledger
            WHERE user_id = %s
            """,
            [user_id],
        )
        row = dict_fetchone(cursor)
    return int(row["balance"])


def update_user_points(user_id):
    balance = get_balance(user_id)
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM user_points WHERE user_id = %s", [user_id])
        existing = dict_fetchone(cursor)
        if existing:
            cursor.execute(
                """
                UPDATE user_points
                SET total_points = %s, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
                """,
                [balance, user_id],
            )
        else:
            cursor.execute(
                "INSERT INTO user_points (user_id, total_points) VALUES (%s, %s)",
                [user_id, balance],
            )
    return balance


def row_by_id(table, row_id):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {table} WHERE id = %s", [row_id])
        return dict_fetchone(cursor)


def table_columns(table):
    with connection.cursor() as cursor:
        cursor.execute(f"PRAGMA table_info({table})")
        return [row[1] for row in cursor.fetchall()]


def list_table(table):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {table} ORDER BY id")
        return dict_fetchall(cursor)


def list_reward_rules():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, CAST(id AS TEXT) AS event_id, event_type, base_points,
                   multiplier, max_points, active, created_at
            FROM reward_rules
            ORDER BY id
            """
        )
        return dict_fetchall(cursor)


def update_allowed_fields(table, row_id, data, allowed_fields):
    updates = {}
    for field in allowed_fields:
        if field not in data:
            continue
        updates[field] = active_value(data) if field == "active" else data[field]
    if not updates:
        return None

    set_clause = ", ".join([f"{field} = %s" for field in updates])
    values = list(updates.values()) + [row_id]
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {table} SET {set_clause} WHERE id = %s", values)
    return updates


def active_value(data):
    if "active" not in data:
        return 1
    value = data["active"]
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, str):
        return 1 if value.lower() in ["1", "true", "yes", "on"] else 0
    return int(value)


def reward_payload(data):
    normalized = dict(data)
    if "reward_code" not in normalized and "code" in normalized:
        normalized["reward_code"] = normalized["code"]
    if "reward_name" not in normalized and "name" in normalized:
        normalized["reward_name"] = normalized["name"]
    return normalized


def user_payload(data):
    normalized = dict(data)
    for alias in ["userId", "customer_id", "customerId"]:
        if "user_id" not in normalized and alias in normalized:
            normalized["user_id"] = normalized[alias]
    return normalized


def selected_user_id(request, user_id=None):
    value = user_id
    for key in ["user_id", "userId", "customer_id", "customerId"]:
        if request.GET.get(key):
            value = request.GET[key]
            break
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def user_has_history(user_id):
    related_tables = ["events", "points_ledger", "user_points", "redemptions"]
    with connection.cursor() as cursor:
        for table in related_tables:
            cursor.execute(f"SELECT 1 FROM {table} WHERE user_id = %s LIMIT 1", [user_id])
            if dict_fetchone(cursor):
                return True
    return False


@csrf_exempt
@json_api_errors
def events_view(request):
    if request.method != "POST":
        return method_not_allowed()

    data = read_json(request)
    if data is None:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)
    data = user_payload(data)

    error = require_fields(
        data,
        ["event_id", "user_id", "event_type", "amount", "event_timestamp"],
    )
    if error:
        return error

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT event_id, points_awarded, processed
                    FROM events
                    WHERE event_id = %s
                    """,
                    [data["event_id"]],
                )
                existing_event = dict_fetchone(cursor)
                if existing_event:
                    return JsonResponse(
                        {
                            "message": "Event already processed",
                            "event": existing_event,
                        },
                        status=200,
                    )

                cursor.execute("SELECT id FROM users WHERE id = %s", [data["user_id"]])
                if not dict_fetchone(cursor):
                    return JsonResponse({"error": "User not found"}, status=404)

                cursor.execute(
                    """
                    SELECT base_points, multiplier, max_points
                    FROM reward_rules
                    WHERE event_type = %s AND active = 1
                    """,
                    [data["event_type"]],
                )
                rule = dict_fetchone(cursor)
                if not rule:
                    return JsonResponse(
                        {"error": "No active reward rule found for event_type"},
                        status=404,
                    )

                points = int(rule["base_points"] * rule["multiplier"])
                if rule["max_points"] is not None:
                    points = min(points, int(rule["max_points"]))

                cursor.execute(
                    """
                    INSERT INTO events
                        (event_id, user_id, event_type, amount, event_timestamp, points_awarded, processed)
                    VALUES (%s, %s, %s, %s, %s, %s, 1)
                    """,
                    [
                        data["event_id"],
                        data["user_id"],
                        data["event_type"],
                        data["amount"],
                        data["event_timestamp"],
                        points,
                    ],
                )
                cursor.execute(
                    """
                    INSERT INTO points_ledger
                        (user_id, event_id, points_earned, description, entry_type)
                    VALUES (%s, %s, %s, %s, 'CREDIT')
                    """,
                    [
                        data["user_id"],
                        data["event_id"],
                        points,
                        f"Points awarded for {data['event_type']}",
                    ],
                )

            balance = update_user_points(data["user_id"])
    except IntegrityError as exc:
        return JsonResponse(
            {"error": "Could not process event", "details": str(exc)},
            status=400,
        )

    return JsonResponse(
        {
            "message": "Event processed",
            "event_id": data["event_id"],
            "points_awarded": points,
            "balance": balance,
        },
        status=201,
    )


@json_api_errors
def event_detail_view(request, event_id):
    if request.method != "GET":
        return method_not_allowed()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, event_id, user_id, event_type, amount, event_timestamp,
                   points_awarded, processed, created_at
            FROM events
            WHERE event_id = %s
            """,
            [event_id],
        )
        event = dict_fetchone(cursor)
    if not event:
        return JsonResponse({"error": "Event not found"}, status=404)
    return JsonResponse({"event": event})


@json_api_errors
def user_balance_view(request, user_id=None):
    if request.method != "GET":
        return method_not_allowed()
    user_id = selected_user_id(request, user_id)
    if user_id is None:
        return JsonResponse({"error": "Missing valid user_id/customer_id"}, status=400)
    return JsonResponse({"user_id": user_id, "balance": get_balance(user_id)})


@json_api_errors
def user_ledger_view(request, user_id=None):
    if request.method != "GET":
        return method_not_allowed()
    user_id = selected_user_id(request, user_id)
    if user_id is None:
        return JsonResponse({"error": "Missing valid user_id/customer_id"}, status=400)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, user_id, event_id, points_earned, description, created_at, entry_type
            FROM points_ledger
            WHERE user_id = %s
            ORDER BY datetime(created_at) DESC, id DESC
            """,
            [user_id],
        )
        ledger = dict_fetchall(cursor)
    return JsonResponse({"user_id": user_id, "ledger": ledger})


@csrf_exempt
@json_api_errors
def redeem_view(request):
    if request.method != "POST":
        return method_not_allowed()

    data = read_json(request)
    if data is None:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)
    data = user_payload(data)

    error = require_fields(data, ["user_id", "reward_code"])
    if error:
        return error

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT id FROM users WHERE id = %s", [data["user_id"]])
                if not dict_fetchone(cursor):
                    return JsonResponse({"error": "User not found"}, status=404)

                cursor.execute(
                    """
                    SELECT reward_code, reward_name, points_required
                    FROM rewards
                    WHERE reward_code = %s AND active = 1
                    """,
                    [data["reward_code"]],
                )
                reward = dict_fetchone(cursor)
                if not reward:
                    return JsonResponse({"error": "Active reward not found"}, status=404)

                balance = get_balance(data["user_id"])
                points_required = int(reward["points_required"])
                if balance < points_required:
                    return JsonResponse(
                        {
                            "error": "Insufficient points",
                            "balance": balance,
                            "points_required": points_required,
                        },
                        status=400,
                    )

                redemption_id = f"RED-{uuid4().hex[:12]}"
                ledger_event_id = f"redemption:{redemption_id}"
                timestamp = timezone.now().replace(microsecond=0).isoformat()

                cursor.execute(
                    """
                    INSERT INTO events
                        (event_id, user_id, event_type, amount, event_timestamp, points_awarded, processed)
                    VALUES (%s, %s, 'REDEMPTION', 0, %s, %s, 1)
                    """,
                    [ledger_event_id, data["user_id"], timestamp, -points_required],
                )
                cursor.execute(
                    """
                    INSERT INTO redemptions
                        (redemption_id, user_id, reward_code, points_spent)
                    VALUES (%s, %s, %s, %s)
                    """,
                    [
                        redemption_id,
                        data["user_id"],
                        data["reward_code"],
                        points_required,
                    ],
                )
                cursor.execute(
                    """
                    INSERT INTO points_ledger
                        (user_id, event_id, points_earned, description, entry_type)
                    VALUES (%s, %s, %s, %s, 'DEBIT')
                    """,
                    [
                        data["user_id"],
                        ledger_event_id,
                        -points_required,
                        f"Redeemed {reward['reward_name']}",
                    ],
                )

            new_balance = update_user_points(data["user_id"])
    except IntegrityError as exc:
        return JsonResponse(
            {"error": "Could not redeem reward", "details": str(exc)},
            status=400,
        )

    return JsonResponse(
        {
            "message": "Reward redeemed",
            "redemption_id": redemption_id,
            "reward_code": data["reward_code"],
            "points_spent": points_required,
            "balance": new_balance,
        },
        status=201,
    )


@csrf_exempt
@json_api_errors
def reverse_event_view(request, event_id):
    if request.method != "POST":
        return method_not_allowed()

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT event_id, user_id, points_awarded, processed
                    FROM events
                    WHERE event_id = %s
                    """,
                    [event_id],
                )
                event = dict_fetchone(cursor)
                if not event:
                    return JsonResponse({"error": "Original event not found"}, status=404)

                cursor.execute(
                    """
                    SELECT id
                    FROM points_ledger
                    WHERE event_id = %s AND entry_type = 'REVERSAL'
                    """,
                    [event_id],
                )
                if event["processed"] == 2 or dict_fetchone(cursor):
                    return JsonResponse({"error": "Event already reversed"}, status=400)

                reversal_points = -int(event["points_awarded"])
                cursor.execute(
                    """
                    INSERT INTO points_ledger
                        (user_id, event_id, points_earned, description, entry_type)
                    VALUES (%s, %s, %s, 'Event reversal', 'REVERSAL')
                    """,
                    [event["user_id"], event_id, reversal_points],
                )
                cursor.execute(
                    "UPDATE events SET processed = 2 WHERE event_id = %s",
                    [event_id],
                )

            balance = update_user_points(event["user_id"])
    except IntegrityError as exc:
        return JsonResponse(
            {"error": "Could not reverse event", "details": str(exc)},
            status=400,
        )

    return JsonResponse(
        {
            "message": "Event reversed",
            "event_id": event_id,
            "points_reversed": reversal_points,
            "balance": balance,
        }
    )


@csrf_exempt
@json_api_errors
def users_view(request):
    if request.method == "GET":
        return JsonResponse({"users": list_table("users")})

    if request.method == "POST":
        data = read_json(request)
        if data is None:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)
        error = require_fields(data, ["name"])
        if error:
            return error

        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO users (name, email) VALUES (%s, %s)",
                    [data["name"], data.get("email")],
                )
                user_id = cursor.lastrowid
        except IntegrityError as exc:
            return JsonResponse(
                {"error": "Could not create user", "details": str(exc)},
                status=400,
            )
        return JsonResponse(
            {"message": "User created", "user": row_by_id("users", user_id)},
            status=201,
        )

    return method_not_allowed()


@csrf_exempt
@json_api_errors
def user_detail_view(request, user_id):
    user = row_by_id("users", user_id)
    if not user:
        return JsonResponse({"error": "User not found"}, status=404)

    if request.method == "GET":
        return JsonResponse({"user": user})

    if request.method in ["PUT", "PATCH"]:
        data = read_json(request)
        if data is None:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)
        allowed_fields = ["name", "email"]
        if "active" in table_columns("users"):
            allowed_fields.append("active")
        try:
            with transaction.atomic():
                if update_allowed_fields("users", user_id, data, allowed_fields) is None:
                    return JsonResponse({"error": "No valid user fields provided"}, status=400)
        except IntegrityError as exc:
            return JsonResponse(
                {"error": "Could not update user", "details": str(exc)},
                status=400,
            )
        return JsonResponse(
            {"message": "User updated", "user": row_by_id("users", user_id)}
        )

    if request.method == "DELETE":
        if user_has_history(user_id):
            return JsonResponse(
                {
                    "error": "Cannot delete user because this user has transactions/ledger history. Mark inactive instead."
                },
                status=400,
            )
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("DELETE FROM users WHERE id = %s", [user_id])
        except IntegrityError as exc:
            return JsonResponse(
                {"error": "Could not delete user", "details": str(exc)},
                status=400,
            )
        return JsonResponse({"message": "User deleted", "id": user_id})

    return method_not_allowed()


@csrf_exempt
@json_api_errors
def reward_rules_view(request):
    if request.method == "GET":
        return JsonResponse({"reward_rules": list_reward_rules()})

    if request.method == "POST":
        data = read_json(request)
        if data is None:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)
        error = require_fields(data, ["event_type", "base_points"])
        if error:
            return error

        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, active FROM reward_rules WHERE event_type = %s",
                    [data["event_type"]],
                )
                existing = dict_fetchone(cursor)
                if existing and int(existing["active"]) == 1:
                    return JsonResponse(
                        {"error": "Reward rule already exists. Use Edit."},
                        status=400,
                    )
                if existing:
                    cursor.execute(
                        """
                        UPDATE reward_rules
                        SET base_points = %s, multiplier = %s, max_points = %s, active = %s
                        WHERE id = %s
                        """,
                        [
                            data["base_points"],
                            data.get("multiplier", 1),
                            data.get("max_points", 100),
                            active_value(data),
                            existing["id"],
                        ],
                    )
                    return JsonResponse(
                        {
                            "message": "Reward rule reactivated",
                            "reward_rule": row_by_id("reward_rules", existing["id"]),
                        },
                        status=200,
                    )

                cursor.execute(
                    """
                    INSERT INTO reward_rules
                        (event_type, base_points, multiplier, max_points, active)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    [
                        data["event_type"],
                        data["base_points"],
                        data.get("multiplier", 1),
                        data.get("max_points", 100),
                        active_value(data),
                    ],
                )
                rule_id = cursor.lastrowid
        except IntegrityError as exc:
            return JsonResponse(
                {"error": "Could not create reward rule", "details": str(exc)},
                status=400,
            )
        return JsonResponse(
            {
                "message": "Reward rule created",
                "reward_rule": row_by_id("reward_rules", rule_id),
            },
            status=201,
        )

    return method_not_allowed()


@csrf_exempt
@json_api_errors
def reward_rule_detail_view(request, rule_id):
    rule = row_by_id("reward_rules", rule_id)
    if not rule:
        return JsonResponse({"error": "Reward rule not found"}, status=404)

    if request.method == "GET":
        return JsonResponse({"reward_rule": rule})

    if request.method in ["PUT", "PATCH"]:
        data = read_json(request)
        if data is None:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)
        try:
            with transaction.atomic():
                updated = update_allowed_fields(
                    "reward_rules",
                    rule_id,
                    data,
                    ["event_type", "base_points", "multiplier", "max_points", "active"],
                )
                if updated is None:
                    return JsonResponse(
                        {"error": "No valid reward rule fields provided"},
                        status=400,
                    )
        except IntegrityError as exc:
            return JsonResponse(
                {"error": "Could not update reward rule", "details": str(exc)},
                status=400,
            )
        return JsonResponse(
            {
                "message": "Reward rule updated",
                "reward_rule": row_by_id("reward_rules", rule_id),
            }
        )

    if request.method == "DELETE":
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("DELETE FROM reward_rules WHERE id = %s", [rule_id])
        return JsonResponse({"message": "Reward rule deleted", "id": rule_id})

    return method_not_allowed()


@csrf_exempt
@json_api_errors
def rewards_view(request):
    if request.method == "GET":
        include_inactive = request.GET.get("include_inactive") == "1"
        with connection.cursor() as cursor:
            if include_inactive:
                cursor.execute(
                    """
                    SELECT id, reward_code, reward_name, points_required, active, created_at
                    FROM rewards
                    ORDER BY id
                    """
                )
            else:
                cursor.execute(
                    """
                    SELECT id, reward_code, reward_name, points_required, active, created_at
                    FROM rewards
                    WHERE active = 1
                    ORDER BY points_required, reward_name
                    """
                )
            rewards = dict_fetchall(cursor)
        return JsonResponse({"rewards": rewards})

    if request.method == "POST":
        data = read_json(request)
        if data is None:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)
        data = reward_payload(data)
        error = require_fields(data, ["reward_code", "reward_name", "points_required"])
        if error:
            return error

        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, active FROM rewards WHERE reward_code = %s",
                    [data["reward_code"]],
                )
                existing = dict_fetchone(cursor)
                if existing and int(existing["active"]) == 1:
                    return JsonResponse(
                        {"error": "Reward code already exists. Use Edit."},
                        status=400,
                    )
                if existing:
                    cursor.execute(
                        """
                        UPDATE rewards
                        SET reward_name = %s, points_required = %s, active = %s
                        WHERE id = %s
                        """,
                        [
                            data["reward_name"],
                            data["points_required"],
                            active_value(data),
                            existing["id"],
                        ],
                    )
                    return JsonResponse(
                        {
                            "message": "Reward reactivated",
                            "reward": row_by_id("rewards", existing["id"]),
                        },
                        status=200,
                    )

                cursor.execute(
                    """
                    INSERT INTO rewards
                        (reward_code, reward_name, points_required, active)
                    VALUES (%s, %s, %s, %s)
                    """,
                    [
                        data["reward_code"],
                        data["reward_name"],
                        data["points_required"],
                        active_value(data),
                    ],
                )
                reward_id = cursor.lastrowid
        except IntegrityError as exc:
            return JsonResponse(
                {"error": "Could not create reward", "details": str(exc)},
                status=400,
            )
        return JsonResponse(
            {"message": "Reward created", "reward": row_by_id("rewards", reward_id)},
            status=201,
        )

    return method_not_allowed()


@csrf_exempt
@json_api_errors
def reward_detail_view(request, reward_id):
    reward = row_by_id("rewards", reward_id)
    if not reward:
        return JsonResponse({"error": "Reward not found"}, status=404)

    if request.method == "GET":
        return JsonResponse({"reward": reward})

    if request.method in ["PUT", "PATCH"]:
        data = read_json(request)
        if data is None:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)
        data = reward_payload(data)
        try:
            with transaction.atomic():
                updated = update_allowed_fields(
                    "rewards",
                    reward_id,
                    data,
                    ["reward_code", "reward_name", "points_required", "active"],
                )
                if updated is None:
                    return JsonResponse({"error": "No valid reward fields provided"}, status=400)
        except IntegrityError as exc:
            return JsonResponse(
                {"error": "Could not update reward", "details": str(exc)},
                status=400,
            )
        return JsonResponse(
            {"message": "Reward updated", "reward": row_by_id("rewards", reward_id)}
        )

    if request.method == "DELETE":
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("DELETE FROM rewards WHERE id = %s", [reward_id])
        return JsonResponse({"message": "Reward deleted", "id": reward_id})

    return method_not_allowed()
