# Daily Food Ordering Skill

## Overview

It's a busy day. You might always think about one thing...What should I eat today?

Yah, this SKILL is for you:)

This project implements a Daily Food Ordering Skill for an AI agent.

The skill automatically selects a meal once per day based on a user's saved preferences, including favorite cuisines, dietary restrictions, budget, and confirmation settings.

This implementation runs entirely in dry-run mode using mock menu data. No real food orders are placed.

## Features

- Reads user preferences from a YAML configuration file (PyYAML, with a robust zero-dependency fallback parser).
- Loads a mock food menu from JSON.
- Filters unavailable menu items.
- Applies generalized dietary restrictions — both lifestyles (`vegetarian`) and exclusions (`no shellfish`, `without pork`, `nut-free`).
- Applies budget constraints.
- Prioritizes preferred cuisines in the user's stated order, then by price.
- Schedule-aware: an `order_time` window check with optional strict skipping.
- Daily variety: remembers recent orders (`order_history.json`) and avoids repeating a meal within `avoid_repeat_days`.
- Confirmation flow: returns `pending_confirmation` until the user approves.
- Degrades gracefully: missing/invalid config or menu returns a structured error, never a traceback.
- Returns a structured JSON recommendation.
- Runs entirely in dry-run mode.

## Project Structure

```text
food-order-skill/
│
├── README.md
├── SKILL.md
├── requirements.txt
├── user_preferences.yaml
├── order_history.json        # generated at runtime (git-ignored)
│
├── tests/
│   └── test_order.py
│
└── src/
    ├── main.py
    └── menu.json
```

## How It Works

1. Load user preferences from `user_preferences.yaml`.
2. Check the `order_time` schedule window (skip in strict mode if outside it).
3. Load available menu items from `menu.json` and drop unavailable ones.
4. Remove items that violate dietary restrictions (lifestyle or exclusion rules).
5. Remove items that exceed the user's budget.
6. Drop items ordered within the last `avoid_repeat_days` days for variety (repeats allowed only if nothing else qualifies).
7. Rank items by the user's cuisine preference order first, then by price.
8. Return the selected meal as a structured JSON response — `pending_confirmation` if approval is required, otherwise `success` (and record placed orders to `order_history.json`).

## Dependencies

The core skill runs on the Python standard library alone. `PyYAML` is
optional but recommended for robust preference parsing; without it, the skill
falls back to a built-in minimal YAML parser. `pytest` is only needed to run
the test suite.

```bash
pip install -r requirements.txt
```

## How to Run

1. Configure your preferences in `user_preferences.yaml`.

2. Update the mock menu in `src/menu.json` if needed.

3. Run the skill:

```bash
python src/main.py                   # dry run with saved preferences
python src/main.py --confirm         # auto-approve (skip pending_confirmation)
python src/main.py --now 12:00       # simulate the current time
python src/main.py --strict-schedule # skip if outside the order_time window
python src/main.py --no-record       # don't persist the order to history
```

The program will load the user preferences, evaluate the available menu, and print a structured JSON result.

## How to Test

Run the test suite:

```bash
python -m pytest -q
```

The tests verify that the core ordering flow runs successfully and that at least one failure path returns a structured fallback response.

## Example Output

Example output after running `python src/main.py` (confirmation required by default):

```json
{
  "mode": "dry_run",
  "restaurant": "Marugame Udon",
  "item": "Beef Udon",
  "cuisine": "Japanese",
  "price_usd": 16,
  "confirmation_required": true,
  "reason": "Selected because it matches the user's top available cuisine preference within budget and dietary restrictions.",
  "status": "pending_confirmation",
  "next_action": "Ask the user to approve this order before it is placed.",
  "scheduled_time": "12:00",
  "within_schedule": true
}
```

Running with `--confirm` returns the same selection with `"status": "success"`.

## Assumptions and Scope

- The skill validates the `order_time` window via `should_run_now` (and can skip with `--strict-schedule`), but an external scheduler (cron, agent runtime) is still responsible for triggering it around that time.
- Food delivery, payment, and restaurant APIs are mocked with local menu data.
- The skill runs in dry-run mode only and never places a real order.
- Preferences are parsed with PyYAML when available, falling back to a built-in parser that supports the flat schema in this repository (including inline comments).
- Dietary restrictions are matched against menu-item `tags`; the matcher handles common lifestyle and exclusion phrasings but is not an exhaustive nutrition database.
- Confirmation is surfaced as `pending_confirmation`; an integrating agent handles the actual user approval channel, then re-runs with approval (`--confirm`).
- Order history is stored locally in `order_history.json` (git-ignored runtime state); only placed (`success`) orders are recorded.

## Future Improvements

- Integrate with food delivery APIs (e.g., Uber Eats or DoorDash).
- Support recurring scheduling.
- Learn from historical ordering behavior.
- Add restaurant ranking based on previous feedback.
