from __future__ import annotations

from typing import Any


COMMON_MERCHANT_WORDS = {"tech", "supplies", "store", "office", "supply"}


def _normalize_merchant_words(name: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in name)
    return [part for part in cleaned.split() if part and part not in COMMON_MERCHANT_WORDS]


def _normalize_merchant_name(name: str) -> str:
    return "".join(_normalize_merchant_words(name))


def _merchant_initials(name: str) -> str:
    return "".join(word[0] for word in _normalize_merchant_words(name) if word)


def _character_overlap(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    left_chars = set(left)
    right_chars = set(right)
    union = left_chars | right_chars
    if not union:
        return 0.0
    return len(left_chars & right_chars) / len(union)


def _merchant_similarity(left: str, right: str) -> bool:
    normalized_left = _normalize_merchant_name(left)
    normalized_right = _normalize_merchant_name(right)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True
    if normalized_left in normalized_right or normalized_right in normalized_left:
        return True
    initials_left = _merchant_initials(left)
    initials_right = _merchant_initials(right)
    if initials_left and initials_left == initials_right and len(initials_left) >= 2:
        return True
    return _character_overlap(normalized_left, normalized_right) >= 0.8


def _set_signal(
    signals: dict[str, dict[str, Any]],
    item_id: str,
    reason: str,
    priority: int,
    explanation: str,
) -> None:
    existing = signals.get(item_id)
    if existing is None or priority < existing["priority"]:
        signals[item_id] = {
            "reason": reason,
            "priority": priority,
            "explanation": explanation,
        }


def detect_fraud_signals(line_items, policy):
    signals: dict[str, dict[str, Any]] = {}

    forbidden_merchants = set(policy.get("forbidden_merchants", []))
    allowed_categories = set(policy.get("allowed_categories", []))
    meal_cap = policy.get("meal_cap")
    require_receipt_over = policy.get("require_receipt_over")

    for item in line_items:
        merchant = item.get("merchant")
        if merchant and merchant in forbidden_merchants:
            _set_signal(
                signals,
                item["item_id"],
                "FORBIDDEN_MERCHANT",
                1,
                f"Merchant {merchant} is explicitly forbidden by company policy",
            )

    laundering_groups: dict[tuple[str, str, float], list[dict[str, Any]]] = {}
    for item in line_items:
        employee_id = item.get("employee_id")
        date = item.get("date")
        amount = item.get("amount")
        if employee_id is None or date is None or amount is None:
            continue
        laundering_groups.setdefault((employee_id, date, float(amount)), []).append(item)

    for items in laundering_groups.values():
        if len(items) < 2:
            continue
        merchants = {item.get("merchant") for item in items if item.get("merchant")}
        if len(merchants) < 2:
            continue
        explanation = "Merchant laundering detected: same employee, date, and amount across different merchants"
        for item in items:
            _set_signal(signals, item["item_id"], "MERCHANT_LAUNDERING", 2, explanation)

    split_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for item in line_items:
        if item.get("category") != "meal":
            continue
        employee_id = item.get("employee_id")
        merchant = item.get("merchant")
        date = item.get("date")
        if employee_id is None or merchant is None or date is None:
            continue
        split_groups.setdefault((employee_id, merchant, date), []).append(item)

    if meal_cap is not None:
        for items in split_groups.values():
            if len(items) < 2:
                continue
            total_amount = sum(float(item.get("amount", 0)) for item in items)
            if total_amount > float(meal_cap):
                explanation = f"Split transactions detected across {len(items)} items exceeding policy cap"
                for item in items:
                    _set_signal(signals, item["item_id"], "SPLIT_TRANSACTION", 3, explanation)

    duplicate_groups: dict[tuple[Any, Any, float, Any], list[dict[str, Any]]] = {}
    for item in line_items:
        merchant = item.get("merchant")
        amount = item.get("amount")
        date = item.get("date")
        if merchant is None or amount is None or date is None:
            continue
        key = (merchant, item.get("employee_id"), float(amount), date)
        duplicate_groups.setdefault(key, []).append(item)

    for items in duplicate_groups.values():
        if len(items) < 2:
            continue
        explanation = f"Duplicate expense detected across {len(items)} matching submissions"
        for item in items:
            _set_signal(signals, item["item_id"], "DUPLICATE_EXPENSE", 4, explanation)

    for item in line_items:
        category = item.get("category")
        merchant = item.get("merchant", "")
        amount = float(item.get("amount", 0))
        item_id = item["item_id"]

        if allowed_categories and category not in allowed_categories:
            _set_signal(
                signals,
                item_id,
                "CATEGORY_MISMATCH",
                5,
                f"Category {category} is not allowed by company policy",
            )
        elif category == "meal" and "hotel" in merchant.lower():
            _set_signal(
                signals,
                item_id,
                "CATEGORY_MISMATCH",
                5,
                "Meal category conflicts with hotel merchant type",
            )

        if meal_cap is not None and category == "meal" and amount > float(meal_cap):
            _set_signal(
                signals,
                item_id,
                "OVER_POLICY_CAP",
                6,
                f"Meal amount {amount:.2f} exceeds policy cap {float(meal_cap):.2f}",
            )

        if (
            not item.get("receipt_attached", True)
            and require_receipt_over is not None
            and amount > float(require_receipt_over)
        ):
            _set_signal(
                signals,
                item_id,
                "MISSING_RECEIPT",
                7,
                f"Receipt required for amount {amount:.2f} above threshold {float(require_receipt_over):.2f}",
            )

    return signals
