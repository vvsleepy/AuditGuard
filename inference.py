import json
import os
import time
import sys
from typing import Any

import requests
from openai import OpenAI

# ✅ FORCE STDOUT FLUSH
sys.stdout.reconfigure(line_buffering=True)

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
MODEL_NAME = os.getenv("MODEL_NAME", "dummy")
HF_TOKEN = os.getenv("HF_TOKEN")
OPENAI_CLIENT = OpenAI(base_url=API_BASE_URL, api_key=HF_TOKEN) if HF_TOKEN else None

BASE_URL = API_BASE_URL
RESET_RETRY_LIMIT = 20
COMMON_MERCHANT_WORDS = {"tech", "supplies", "store", "office", "supply"}


def _format_done(value: bool) -> str:
    return "true" if value else "false"


def _format_error(value: str | None) -> str:
    return "null" if value is None else value


def _format_reward(value: float) -> str:
    return format(value, ".2f")


def _post_json(path: str, payload: dict | None = None) -> dict:
    response = requests.post(f"{BASE_URL}{path}", json=payload, timeout=10)
    response.raise_for_status()
    return response.json()


def _resolve_task_path(task_file: str) -> str:
    base_dir = os.path.dirname(__file__)
    if os.path.isabs(task_file):
        return task_file
    if task_file.startswith("data/"):
        return os.path.join(base_dir, task_file)
    return os.path.join(base_dir, "data", task_file)


def _load_requested_task_id(task_file: str) -> str:
    task_path = _resolve_task_path(task_file)
    with open(task_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise ValueError(f"Requested task file is missing a valid task_id: {task_file}")
    return task_id


def _reset_with_optional_forced_task() -> dict:
    task_file = os.getenv("AUDITGUARD_TASK_FILE")
    if not task_file:
        return _post_json("/reset")

    expected_task_id = _load_requested_task_id(task_file)
    last_payload: dict[str, Any] | None = None

    for _ in range(RESET_RETRY_LIMIT):
        last_payload = _post_json("/reset")
        observation = last_payload.get("observation", {})
        if observation.get("task_id") == expected_task_id:
            return last_payload
        time.sleep(0.2)

    if last_payload is None:
        raise RuntimeError("Failed to reset environment.")
    return last_payload


# ===========================
# (NO CHANGES BELOW — SAME LOGIC)
# ===========================

def _normalize_merchant_words(name: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in name)
    return [part for part in cleaned.split() if part and part not in COMMON_MERCHANT_WORDS]


def _normalize_merchant_name(name: str) -> str:
    return "".join(_normalize_merchant_words(name))


def _merchant_initials(name: str) -> str:
    words = _normalize_merchant_words(name)
    return "".join(word[0] for word in words if word)


def _character_overlap(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    left_chars = set(left)
    right_chars = set(right)
    union = left_chars | right_chars
    if not union:
        return 0.0
    return len(left_chars & right_chars) / len(union)


def _merchant_similarity_strict(left: str, right: str) -> bool:
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


def _is_missing_receipt(item: dict, company_policy: dict) -> bool:
    require_receipt_over = company_policy.get("require_receipt_over")
    return (
        not item.get("receipt_attached", True)
        and require_receipt_over is not None
        and float(item.get("amount", 0)) > float(require_receipt_over)
    )


def _is_forbidden_merchant(item: dict, company_policy: dict) -> bool:
    merchant = item.get("merchant")
    forbidden_merchants = company_policy.get("forbidden_merchants", [])
    return bool(merchant and merchant in forbidden_merchants)


def _is_category_mismatch(item: dict) -> bool:
    merchant = (item.get("merchant") or "").lower()
    category = item.get("category")
    return category == "meal" and "hotel" in merchant


def _is_over_policy_cap(item: dict, company_policy: dict) -> bool:
    meal_cap = company_policy.get("meal_cap")
    return (
        meal_cap is not None
        and item.get("category") == "meal"
        and float(item.get("amount", 0)) > float(meal_cap)
    )


def _is_ambiguous(item: dict) -> bool:
    description = (item.get("description") or "").lower()
    ambiguous_terms = (
        "unclear",
        "unknown",
        "not specified",
        "adjustment",
    )
    return any(term in description for term in ambiguous_terms)


def _split_transaction_item_ids(line_items: list[dict], company_policy: dict) -> set[str]:
    meal_cap = company_policy.get("meal_cap")
    if meal_cap is None:
        return set()

    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for item in line_items:
        if item.get("category") != "meal":
            continue
        employee_id = item.get("employee_id")
        merchant = item.get("merchant")
        date = item.get("date")
        if not employee_id or not merchant or not date:
            continue
        grouped.setdefault((employee_id, merchant, date), []).append(item)

    flagged: set[str] = set()
    for items in grouped.values():
        if len(items) < 2:
            continue

        amounts = [float(i.get("amount", 0)) for i in items]
        if not all(amount <= float(meal_cap) for amount in amounts):
            continue

        if sum(amounts) > float(meal_cap):
            flagged.update(i["item_id"] for i in items)

    return flagged


def main() -> None:
    rewards: list[str] = []
    steps = 0
    success = False

    try:
        obs = _reset_with_optional_forced_task()["observation"]
        print(f"[START] task={obs['task_id']} env=auditguard model={MODEL_NAME}", flush=True)

        done = bool(obs.get("done", False))
        while not done:
            action = _next_action(obs)
            steps += 1

            action_type = action["action_type"]
            if action_type in {"flag_item", "approve_item", "request_info"}:
                action_label = f"{action_type}({action['item_id']})"
            else:
                action_label = action_type

            res = _post_json("/step", {"action": action})
            obs = res["observation"]
            reward = float(res["reward"])
            done = bool(res["done"])
            info = res.get("info", {})
            error = info.get("error")

            rewards.append(_format_reward(reward))

            print(
                f"[STEP] step={steps} action={action_label} "
                f"reward={_format_reward(reward)} done={_format_done(done)} error={_format_error(error)}",
                flush=True
            )

        success = True
    except Exception as exc:
        print(f"FATAL: {exc}", flush=True)
        success = False
    finally:
        print(
            f"[END] success={_format_done(success)} steps={steps} rewards={','.join(rewards)}",
            flush=True
        )


if __name__ == "__main__":
    main()