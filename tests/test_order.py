import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import json

from main import (
    load_preferences,
    load_menu,
    select_order,
    run_order,
    should_run_now,
    violates_diet,
    recent_order_keys,
    record_order,
)


def test_core_ordering_flow():
    preferences = load_preferences()
    menu = load_menu()
    result = select_order(preferences, menu, confirmed=True)

    assert result["status"] == "success"
    assert result["mode"] == "dry_run"
    assert result["restaurant"] == "Marugame Udon"
    assert result["item"] == "Beef Udon"
    assert result["price_usd"] <= preferences["budget_max_usd"]


def test_budget_failure_path_returns_fallback():
    preferences = {
        "budget_max_usd": 10,
        "favorite_cuisines": ["Japanese"],
        "dietary_restrictions": ["no shellfish"],
        "confirmation_required": True,
    }
    menu = [
        {
            "restaurant": "Marugame Udon",
            "item": "Beef Udon",
            "cuisine": "Japanese",
            "price": 16,
            "tags": ["beef"],
            "available": True,
        }
    ]

    result = select_order(preferences, menu)

    assert result["status"] == "failed"
    assert "budget" in result["reason"]
    assert "fallback" in result


def test_missing_menu_returns_structured_error():
    result = run_order(menu_path=PROJECT_ROOT / "src" / "does_not_exist.json")

    assert result["status"] == "failed"
    assert "Menu data is unavailable" in result["reason"]
    assert "fallback" in result


def test_confirmation_required_returns_pending():
    preferences = {
        "budget_max_usd": 20,
        "favorite_cuisines": ["Japanese"],
        "dietary_restrictions": [],
        "confirmation_required": True,
    }
    menu = [
        {
            "restaurant": "Marugame Udon",
            "item": "Beef Udon",
            "cuisine": "Japanese",
            "price": 16,
            "tags": ["beef"],
            "available": True,
        }
    ]

    pending = select_order(preferences, menu, confirmed=False)
    assert pending["status"] == "pending_confirmation"
    assert pending["restaurant"] == "Marugame Udon"
    assert "next_action" in pending

    approved = select_order(preferences, menu, confirmed=True)
    assert approved["status"] == "success"


def test_dietary_restrictions_generalized():
    menu = [
        {"restaurant": "A", "item": "Pork Bowl", "cuisine": "Chinese",
         "price": 10, "tags": ["pork"], "available": True},
        {"restaurant": "B", "item": "Veggie Bowl", "cuisine": "Healthy",
         "price": 12, "tags": ["vegetarian"], "available": True},
        {"restaurant": "C", "item": "Shrimp Plate", "cuisine": "Seafood",
         "price": 14, "tags": ["shellfish"], "available": True},
    ]

    # "vegetarian" lifestyle requires the tag.
    assert violates_diet(menu[0], ["vegetarian"]) is True
    assert violates_diet(menu[1], ["vegetarian"]) is False

    # "no pork" / "no shellfish" exclusion.
    assert violates_diet(menu[0], ["no pork"]) is True
    assert violates_diet(menu[2], ["no shellfish"]) is True
    assert violates_diet(menu[1], ["no shellfish"]) is False


def test_cuisine_priority_beats_lower_price():
    """Top-ranked cuisine wins even when a lower-ranked cuisine is cheaper."""
    preferences = {
        "budget_max_usd": 30,
        "favorite_cuisines": ["Japanese", "Mediterranean"],
        "dietary_restrictions": [],
        "confirmation_required": False,
    }
    menu = [
        {"restaurant": "Cheap Med", "item": "Falafel", "cuisine": "Mediterranean",
         "price": 12, "tags": ["vegetarian"], "available": True},
        {"restaurant": "Pricier JP", "item": "Sushi Set", "cuisine": "Japanese",
         "price": 25, "tags": ["fish"], "available": True},
    ]

    result = select_order(preferences, menu)
    assert result["status"] == "success"
    assert result["cuisine"] == "Japanese"


def test_should_run_now_window():
    noon = datetime(2026, 1, 1, 12, 0)
    assert should_run_now("12:00", now=noon) is True
    assert should_run_now("12:30", now=noon, window_minutes=60) is True
    # 4 hours away is outside the default 2-hour window.
    assert should_run_now("16:30", now=noon, window_minutes=120) is False
    # Missing/blank schedule never blocks.
    assert should_run_now("", now=noon) is True


def test_strict_schedule_skips_outside_window():
    eight_am = datetime(2026, 1, 1, 8, 0)
    result = run_order(now=eight_am, strict_schedule=True, window_minutes=60)
    assert result["status"] == "skipped"
    assert "scheduled_time" in result


def test_recent_order_keys_window():
    now = datetime(2026, 1, 10, 12, 0)
    history = [
        {"date": "2026-01-10", "restaurant": "A", "item": "X"},   # today
        {"date": "2026-01-08", "restaurant": "B", "item": "Y"},   # 2 days ago
        {"date": "2026-01-01", "restaurant": "C", "item": "Z"},   # 9 days ago
    ]
    keys = recent_order_keys(history, days=3, now=now)
    assert ("A", "X") in keys
    assert ("B", "Y") in keys
    assert ("C", "Z") not in keys
    assert recent_order_keys(history, days=0, now=now) == set()


def test_select_order_avoids_recent_repeat():
    preferences = {
        "budget_max_usd": 30,
        "favorite_cuisines": ["Japanese", "Mediterranean"],
        "dietary_restrictions": [],
        "confirmation_required": False,
    }
    menu = [
        {"restaurant": "Marugame Udon", "item": "Beef Udon", "cuisine": "Japanese",
         "price": 16, "tags": ["beef"], "available": True},
        {"restaurant": "Sweetgreen", "item": "Harvest Bowl", "cuisine": "Mediterranean",
         "price": 17, "tags": ["vegetarian"], "available": True},
    ]

    recent = {("Marugame Udon", "Beef Udon")}
    result = select_order(preferences, menu, recent_orders=recent)

    assert result["status"] == "success"
    assert result["item"] == "Harvest Bowl"
    assert result["avoided_recent_repeat"] is True


def test_repeat_allowed_when_all_recent():
    preferences = {
        "budget_max_usd": 30,
        "favorite_cuisines": ["Japanese"],
        "dietary_restrictions": [],
        "confirmation_required": False,
    }
    menu = [
        {"restaurant": "Marugame Udon", "item": "Beef Udon", "cuisine": "Japanese",
         "price": 16, "tags": ["beef"], "available": True},
    ]

    recent = {("Marugame Udon", "Beef Udon")}
    result = select_order(preferences, menu, recent_orders=recent)

    assert result["status"] == "success"
    assert result["item"] == "Beef Udon"
    assert result["avoided_recent_repeat"] is False
    assert "repeat" in result["reason"].lower()


def test_run_order_records_history(tmp_path):
    history_file = tmp_path / "order_history.json"
    today = datetime(2026, 1, 1, 12, 0)

    result = run_order(
        history_path=history_file,
        now=today,
        confirmed=True,
    )

    assert result["status"] == "success"
    saved = json.loads(history_file.read_text())
    assert len(saved) == 1
    assert saved[0]["item"] == result["item"]
    assert saved[0]["date"] == "2026-01-01"
