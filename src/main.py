import argparse
import json
from datetime import datetime
from pathlib import Path

try:
    import yaml  # PyYAML, preferred parser when available
    _HAS_YAML = True
except ImportError:  # keep the skill runnable with zero dependencies
    _HAS_YAML = False


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PREFERENCES_PATH = PROJECT_ROOT / "user_preferences.yaml"
MENU_PATH = PROJECT_ROOT / "src" / "menu.json"
HISTORY_PATH = PROJECT_ROOT / "order_history.json"

DEFAULT_SCHEDULE_WINDOW_MINUTES = 120

# Restrictions phrased as a lifestyle require the menu item to carry the tag.
LIFESTYLE_TAGS = {"vegetarian", "vegan", "halal", "kosher", "pescatarian"}

# Common ways users phrase an "exclude this ingredient" restriction.
_EXCLUDE_PREFIXES = ("no ", "without ", "avoid ", "no-", "not ")


def _strip_inline_comment(value):
    """Remove a trailing `# comment` that is not inside a quoted string."""
    quote = None
    result = []

    for char in value:
        if char in ('"', "'"):
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            result.append(char)
        elif char == "#" and quote is None:
            break
        else:
            result.append(char)

    return "".join(result).strip()


def _coerce_scalar(value):
    """Convert a raw YAML scalar string into a typed Python value."""
    value = _strip_inline_comment(value).strip().strip('"').strip("'")

    if value == "":
        return ""
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.lstrip("-").isdigit():
        return int(value)

    return value


def _fallback_parse_yaml(text):
    """Minimal YAML parser used only when PyYAML is unavailable.

    Supports the flat schema this skill needs: scalar keys plus simple
    `- item` lists. It strips inline comments so the reference schema
    (which uses trailing `# ...` comments) parses correctly.
    """
    preferences = {}
    current_key = None

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if line.startswith("- ") and current_key:
            item = _strip_inline_comment(line[2:]).strip().strip('"').strip("'")
            preferences[current_key].append(item)
            continue

        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = _strip_inline_comment(value).strip()

            if value == "":
                preferences[key] = []
                current_key = key
            else:
                preferences[key] = _coerce_scalar(value)
                current_key = None

    return preferences


def load_preferences(path=PREFERENCES_PATH):
    with open(path, "r", encoding="utf-8") as file:
        text = file.read()

    if _HAS_YAML:
        parsed = yaml.safe_load(text) or {}
        if not isinstance(parsed, dict):
            raise ValueError("Preferences file must define a mapping of settings.")
        return parsed

    return _fallback_parse_yaml(text)


def load_menu(path=MENU_PATH):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _item_tags(item):
    """Normalized set of dietary/ingredient tags for a menu item.

    Supports both the modern `tags` list and the legacy `shellfish` boolean.
    """
    tags = {str(tag).lower() for tag in item.get("tags", [])}
    if item.get("shellfish") is True:
        tags.add("shellfish")
    return tags


def violates_diet(item, restrictions):
    """Return True if the item breaks any dietary restriction.

    Handles two restriction styles:
      - lifestyle (e.g. "vegetarian"): the item must carry that tag.
      - exclusion (e.g. "no shellfish", "without pork", "nut-free"): the
        item must not carry the named ingredient tag.
    """
    tags = _item_tags(item)

    for restriction in restrictions:
        rule = str(restriction).lower().strip()
        if not rule:
            continue

        lifestyle = next((life for life in LIFESTYLE_TAGS if life in rule), None)
        if lifestyle:
            if lifestyle not in tags:
                return True
            continue

        keyword = rule
        for prefix in _EXCLUDE_PREFIXES:
            if keyword.startswith(prefix):
                keyword = keyword[len(prefix):]
                break
        keyword = keyword.replace("-free", "").replace(" free", "").strip()

        if keyword and any(keyword in tag for tag in tags):
            return True

    return False


def should_run_now(order_time, now=None, window_minutes=DEFAULT_SCHEDULE_WINDOW_MINUTES):
    """Return True if `now` falls within `window_minutes` of the scheduled time.

    If `order_time` is missing or unparseable, scheduling is not enforced
    (returns True) so the skill never silently blocks on bad config.
    """
    if not order_time:
        return True

    now = now or datetime.now()

    try:
        hour, minute = (int(part) for part in str(order_time).split(":"))
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except (ValueError, TypeError):
        return True

    delta_minutes = abs((now - scheduled).total_seconds()) / 60
    return delta_minutes <= window_minutes


def load_history(path=HISTORY_PATH):
    """Load past orders. Missing or corrupt history is treated as empty."""
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    return data if isinstance(data, list) else []


def _order_key(record):
    return (record.get("restaurant"), record.get("item"))


def recent_order_keys(history, days, now=None):
    """Return the set of (restaurant, item) keys ordered within `days`.

    `days <= 0` (or falsy) disables de-duplication and returns an empty set.
    """
    if not days or days <= 0:
        return set()

    today = (now or datetime.now()).date()
    keys = set()

    for record in history:
        raw_date = record.get("date")
        try:
            order_date = datetime.fromisoformat(str(raw_date)).date()
        except (TypeError, ValueError):
            continue

        if 0 <= (today - order_date).days < days:
            keys.add(_order_key(record))

    return keys


def record_order(order, path=HISTORY_PATH, now=None):
    """Append a placed order to the history file (dry-run simulated placement)."""
    today = (now or datetime.now()).date().isoformat()
    history = load_history(path)
    history.append({
        "date": today,
        "restaurant": order.get("restaurant"),
        "item": order.get("item"),
        "cuisine": order.get("cuisine"),
        "price_usd": order.get("price_usd"),
    })

    with open(path, "w", encoding="utf-8") as file:
        json.dump(history, file, indent=2)

    return history


def select_order(preferences, menu, confirmed=False, recent_orders=None):
    budget = preferences.get("budget_max_usd")
    favorite_cuisines = preferences.get("favorite_cuisines", [])
    dietary_restrictions = preferences.get("dietary_restrictions", [])
    confirmation_required = preferences.get("confirmation_required", True)

    if budget is None:
        return {
            "status": "failed",
            "reason": "Missing budget_max_usd in user preferences.",
            "fallback": "Ask the user to complete the configuration."
        }

    try:
        budget = float(budget)
    except (TypeError, ValueError):
        return {
            "status": "failed",
            "reason": "budget_max_usd must be a number.",
            "fallback": "Ask the user to set a numeric budget."
        }

    available_items = [item for item in menu if item.get("available") is True]

    diet_safe_items = [
        item for item in available_items
        if not violates_diet(item, dietary_restrictions)
    ]

    budget_safe_items = [
        item for item in diet_safe_items
        if item.get("price", 999999) <= budget
    ]

    if not budget_safe_items:
        return {
            "status": "failed",
            "reason": "No available menu item was within the user's budget and dietary restrictions.",
            "fallback": "Ask the user to increase the budget or choose manually."
        }

    recent_orders = recent_orders or set()
    fresh_items = [
        item for item in budget_safe_items
        if _order_key(item) not in recent_orders
    ]

    # Prefer variety, but never block an order just because everything was
    # ordered recently — fall back to the full list and note the repeat.
    if fresh_items:
        candidate_items = fresh_items
        repeated_recent = False
    else:
        candidate_items = budget_safe_items
        repeated_recent = bool(recent_orders)

    def cuisine_rank(item):
        """Lower rank = stronger preference; favorites are ordered."""
        cuisine = item.get("cuisine")
        if cuisine in favorite_cuisines:
            return favorite_cuisines.index(cuisine)
        return len(favorite_cuisines)

    favorite_cuisine_items = [
        item for item in candidate_items
        if item.get("cuisine") in favorite_cuisines
    ]

    if favorite_cuisine_items:
        # Honor the user's cuisine ordering first, then prefer the cheaper option.
        selected = sorted(
            favorite_cuisine_items,
            key=lambda item: (cuisine_rank(item), item["price"])
        )[0]
        reason = "Selected because it matches the user's top available cuisine preference within budget and dietary restrictions."
    else:
        selected = sorted(candidate_items, key=lambda item: item["price"])[0]
        reason = "Selected as the best available option within budget and dietary restrictions."

    if repeated_recent:
        reason += " Note: all eligible options were ordered recently, so a repeat was allowed."

    order = {
        "mode": "dry_run",
        "restaurant": selected["restaurant"],
        "item": selected["item"],
        "cuisine": selected["cuisine"],
        "price_usd": selected["price"],
        "confirmation_required": confirmation_required,
        "reason": reason,
    }

    if recent_orders:
        order["avoided_recent_repeat"] = not repeated_recent

    if confirmation_required and not confirmed:
        order["status"] = "pending_confirmation"
        order["next_action"] = "Ask the user to approve this order before it is placed."
    else:
        order["status"] = "success"
        order["next_action"] = "Order approved (dry run); no real order was placed."

    return order


def run_order(
    preferences_path=PREFERENCES_PATH,
    menu_path=MENU_PATH,
    history_path=HISTORY_PATH,
    now=None,
    strict_schedule=False,
    confirmed=False,
    record=True,
    window_minutes=DEFAULT_SCHEDULE_WINDOW_MINUTES,
):
    """Orchestrate the full flow and always return a structured result.

    File-load failures and out-of-schedule runs are translated into
    structured responses so the skill degrades gracefully instead of
    raising raw tracebacks.
    """
    try:
        preferences = load_preferences(preferences_path)
    except FileNotFoundError:
        return {
            "status": "failed",
            "reason": "User preferences file was not found.",
            "fallback": "Ask the user to complete the configuration before running the skill."
        }
    except Exception as error:
        return {
            "status": "failed",
            "reason": f"User preferences could not be parsed: {error}",
            "fallback": "Ask the user to fix the preferences file."
        }

    order_time = preferences.get("order_time")
    within_schedule = should_run_now(order_time, now=now, window_minutes=window_minutes)

    if strict_schedule and not within_schedule:
        return {
            "status": "skipped",
            "reason": f"Current time is outside the scheduled order window ({order_time}).",
            "scheduled_time": order_time,
            "fallback": "The skill will run automatically at the next scheduled time."
        }

    try:
        menu = load_menu(menu_path)
    except FileNotFoundError:
        return {
            "status": "failed",
            "reason": "Menu data is unavailable.",
            "fallback": "Stop execution and retry once the menu can be loaded."
        }
    except Exception as error:
        return {
            "status": "failed",
            "reason": f"Menu data could not be parsed: {error}",
            "fallback": "Stop execution and retry once the menu is valid."
        }

    avoid_repeat_days = preferences.get("avoid_repeat_days", 0)
    recent_orders = recent_order_keys(load_history(history_path), avoid_repeat_days, now=now)

    result = select_order(
        preferences, menu, confirmed=confirmed, recent_orders=recent_orders
    )

    if result.get("status") in ("success", "pending_confirmation"):
        result["scheduled_time"] = order_time
        result["within_schedule"] = within_schedule

    # Only a placed order (success) is written to history; a pending order
    # has not actually been ordered yet.
    if record and result.get("status") == "success":
        record_order(result, path=history_path, now=now)

    return result


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Daily Food Ordering Skill (dry-run). Selects a meal from saved preferences."
    )
    parser.add_argument(
        "--now",
        metavar="HH:MM",
        help="Simulate the current time (e.g. 12:00) to demonstrate scheduling.",
    )
    parser.add_argument(
        "--strict-schedule",
        action="store_true",
        help="Skip ordering when outside the scheduled order_time window.",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=DEFAULT_SCHEDULE_WINDOW_MINUTES,
        help="Scheduling window in minutes around order_time (default: 120).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Auto-approve the order (skip the pending_confirmation step).",
    )
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="Do not write a placed order to the history file.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)

    now = None
    if args.now:
        try:
            hour, minute = (int(part) for part in args.now.split(":"))
            now = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        except (ValueError, TypeError):
            print(json.dumps({
                "status": "failed",
                "reason": f"Invalid --now value: {args.now}. Use HH:MM.",
                "fallback": "Provide a 24-hour time such as 12:00."
            }, indent=2))
            return

    result = run_order(
        now=now,
        strict_schedule=args.strict_schedule,
        confirmed=args.confirm,
        record=not args.no_record,
        window_minutes=args.window,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
