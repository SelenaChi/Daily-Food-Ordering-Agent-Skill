---
name: daily-food-ordering
description: Automatically orders food for a user once per day using saved preferences.
---
# Daily Food Ordering Skill

## Skill Purpose

This skill helps an AI agent automatically choose a meal for a user once per day based on their saved preferences.

The goal is to reduce repetitive decision-making while respecting the user's budget, dietary restrictions, and favorite cuisines.

This implementation runs in dry-run mode. It demonstrates the decision-making process without placing a real food order.

## When to Invoke

The agent should invoke this skill when:

- The scheduled food ordering time is reached.
- The user asks the agent to order lunch or dinner.
- The user requests today's meal recommendation.

The agent should not invoke this skill when:

- User preferences have not been configured.
- The user has disabled automatic ordering.
- The user only wants restaurant suggestions without placing an order.

## Execution Instructions

When this skill is executed, the agent should follow these steps:

1. Load the user's preference configuration.
2. Check the schedule: confirm the current time is within the `order_time` window. In strict mode, skip the run (and retry at the next scheduled time) if it is not.
3. Load the available food menu and drop unavailable items.
4. Remove menu items that violate dietary restrictions. Restrictions may be:
   - a lifestyle (e.g. `vegetarian`, `vegan`) — the item must carry that tag, or
   - an exclusion (e.g. `no shellfish`, `without pork`, `nut-free`) — the item must not contain that ingredient tag.
5. Remove menu items that exceed the user's budget.
6. Avoid repeats: drop items ordered within the last `avoid_repeat_days` days (based on order history) to keep daily variety. If every eligible item was ordered recently, allow a repeat rather than skip the meal, and note it.
7. Rank the remaining items by the user's cuisine preference order first, then by price.
8. Select the best available menu item.
9. If `confirmation_required` is true, return a `pending_confirmation` result and ask the user to approve before placing the order.
10. Otherwise (or once approved), return a `success` result and record the placed order to history.
11. Return a structured response describing the selected meal and the reason it was chosen.

## User Configuration

The skill uses a YAML configuration file to store user preferences.

Example configuration:

```yaml
order_time: "12:00"

favorite_cuisines:
  - Japanese
  - Mediterranean

dietary_restrictions:
  - no shellfish

budget_max_usd: 20

confirmation_required: true

avoid_repeat_days: 3   # don't reorder the same meal within this many days (0 disables)
```

## Output Format

The skill returns a structured JSON result after making a decision. The `status`
field tells the agent what to do next.

When confirmation is required, the order is returned as `pending_confirmation`:

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

Once approved (or when confirmation is not required), the status becomes `success`.

If the run is triggered outside the scheduled window in strict mode, the skill
returns a `skipped` result instead of ordering:

```json
{
  "status": "skipped",
  "reason": "Current time is outside the scheduled order window (12:00).",
  "scheduled_time": "12:00",
  "fallback": "The skill will run automatically at the next scheduled time."
}
```

## Command-Line Usage

```bash
python src/main.py                      # run with saved preferences (dry run)
python src/main.py --confirm            # auto-approve, skip pending_confirmation
python src/main.py --now 12:00          # simulate the current time
python src/main.py --strict-schedule    # skip if outside the order_time window
python src/main.py --window 60          # set the schedule window (minutes)
```

## Error Handling

If no menu item is within the user's budget:

- Return a failure message.
- Suggest increasing the budget or skipping today's order.

If no menu item matches the user's dietary restrictions:

- Return a failure message.
- Ask the user to update their preferences or choose manually.

If no preferred cuisine is available:

- Select another available item within budget and explain the decision.

If the menu cannot be loaded:

- Stop execution.
- Return an error explaining that menu data is unavailable.

If user preferences are missing:

- Stop execution.
- Ask the user to complete the configuration before running the skill.

## Assumptions

- This implementation uses mock menu data instead of a real food delivery service.
- No real food order or payment is placed.
- The skill is demonstrated in dry-run mode.
- The menu data is assumed to be available locally, with each item carrying `tags` describing ingredients/diet (legacy `shellfish` boolean is still supported).
- The skill is schedule-aware via `should_run_now`, but an external scheduler (cron, agent runtime) is still responsible for triggering it around `order_time`.
- Placed orders are appended to a local `order_history.json` to drive daily variety; only `success` orders are recorded (a `pending_confirmation` order is not yet placed).
- Future versions can integrate with real delivery platforms such as Uber Eats or DoorDash.

## Future Improvements

- Support multiple meals per day.
- Learn richer signals from order history (ratings, rotation across cuisines).
- Integrate with real delivery services and a confirmation channel (push/SMS).