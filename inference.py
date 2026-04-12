import json
import os
import time
import requests
import sys
from pathlib import Path

# if hasattr(sys.stdout, "reconfigure"):
#     sys.stdout.reconfigure(line_buffering=True)


os.environ["PYTHONUNBUFFERED"] = "1"

def _get_all_task_files():
    task_file = os.getenv("AUDITGUARD_TASK_FILE")

    base_dir = Path(__file__).parent / "data"

    if task_file:
        return [task_file]

    return [
        f.name for f in base_dir.glob("*.json")
        if f.name.startswith("task_")
    ]

sys.stdout.reconfigure(line_buffering=True)

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:7860")
MODEL_NAME = os.getenv("MODEL_NAME", "dummy")
HF_TOKEN = os.getenv("HF_TOKEN")

BASE_URL = API_BASE_URL
RESET_RETRY_LIMIT = 20
COMMON_MERCHANT_WORDS = {"tech", "supplies", "store", "office", "supply"}


def _wait_for_server():
    for _ in range(60):  # wait longer
        try:
            requests.get(f"{BASE_URL}/docs", timeout=2)
            return
        except:
            time.sleep(1)

    # DO NOT CRASH
    return

# def _call_llm_once():
#     try:
#         base_url = os.environ.get("API_BASE_URL")
#         api_key = os.environ.get("API_KEY")

#         if not base_url or not api_key:
#             return

#         client = OpenAI(base_url=base_url, api_key=api_key)
#         client.chat.completions.create(
#             model="gpt-3.5-turbo",
#             messages=[{"role": "user", "content": "audit"}],
#             max_tokens=5
#         )
#     except Exception:
#         pass


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
    ambiguous_terms = ("unclear", "unknown", "not specified", "adjustment")
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


def _merchant_laundering_item_ids(line_items: list[dict]) -> set[str]:
    grouped: dict[tuple[str, str, float], list[dict]] = {}
    for item in line_items:
        employee_id = item.get("employee_id")
        date = item.get("date")
        amount = item.get("amount")
        if employee_id is None or date is None or amount is None:
            continue
        grouped.setdefault((employee_id, date, float(amount)), []).append(item)

    flagged: set[str] = set()
    for items in grouped.values():
        if len(items) < 2:
            continue
        merchants = [i.get("merchant") for i in items if i.get("merchant")]
        if len(set(merchants)) < 2:
            continue
        for item in items:
            flagged.add(item["item_id"])

    return flagged


def _duplicate_item_ids(line_items: list[dict]) -> set[str]:
    first_seen: dict[tuple[str, str, float, str], str] = {}
    flagged: set[str] = set()

    for item in line_items:
        merchant = item.get("merchant")
        employee_id = item.get("employee_id")
        amount = item.get("amount")
        date = item.get("date")

        if merchant is None or employee_id is None or amount is None or date is None:
            continue

        key = (merchant, employee_id, float(amount), date)
        if key in first_seen:
            flagged.add(item["item_id"])
        else:
            first_seen[key] = item["item_id"]

    return flagged


def _build_fraud_signals(observation: dict) -> dict[str, dict[str, Any]]:
    line_items = observation.get("line_items", [])
    policy = observation.get("company_policy", {})

    split_ids = _split_transaction_item_ids(line_items, policy)
    laundering_ids = _merchant_laundering_item_ids(line_items)
    duplicate_ids = _duplicate_item_ids(line_items)

    signals: dict[str, dict[str, Any]] = {}

    for item in line_items:
        item_id = item["item_id"]
        reason: str | None = None
        priority: int | None = None

        if _is_forbidden_merchant(item, policy):
            reason = "FORBIDDEN_MERCHANT"
            priority = 1
        elif item_id in laundering_ids:
            reason = "MERCHANT_LAUNDERING"
            priority = 2
        elif item_id in split_ids:
            reason = "SPLIT_TRANSACTION"
            priority = 3
        elif item_id in duplicate_ids:
            reason = "DUPLICATE_EXPENSE"
            priority = 4
        elif _is_category_mismatch(item):
            reason = "CATEGORY_MISMATCH"
            priority = 5
        elif _is_over_policy_cap(item, policy):
            reason = "OVER_POLICY_CAP"
            priority = 6
        elif _is_missing_receipt(item, policy):
            reason = "MISSING_RECEIPT"
            priority = 7

        signals[item_id] = {
            "reason": reason,
            "priority": priority,
            "ambiguous": _is_ambiguous(item),
        }

    return signals


def _remaining_steps(observation: dict) -> int:
    max_steps = observation.get("max_steps", 0)
    step_count = observation.get("step_count", 0)
    remaining_by_steps = max(max_steps - step_count, 0)
    remaining_by_budget = observation.get("remaining_audit_budget")
    if isinstance(remaining_by_budget, int):
        return min(remaining_by_steps, remaining_by_budget)
    return remaining_by_steps


def _next_action(observation: dict) -> dict:
    already_flagged = observation.get("already_flagged", [])
    flagged_ids = {entry["item_id"] for entry in already_flagged}
    approved_ids = set(observation.get("already_approved", []))
    requested_ids = {entry["item_id"] for entry in observation.get("requests_sent", [])}
    processed_ids = flagged_ids | approved_ids | requested_ids

    last_action_type = observation.get("last_action_result", {}).get("action_type")
    remaining_steps = _remaining_steps(observation)

    if last_action_type == "set_batch_decision":
        return {"action_type": "finalize"}

    if remaining_steps <= 2:
        decision = "partial_reject" if flagged_ids else "approve"
        return {"action_type": "set_batch_decision", "decision": decision}

    signals = _build_fraud_signals(observation)

    candidates: list[tuple[int, str, str]] = []
    for item in observation.get("line_items", []):
        item_id = item["item_id"]
        if item_id in processed_ids:
            continue

        reason = signals[item_id]["reason"]
        priority = signals[item_id]["priority"]
        ambiguous = signals[item_id]["ambiguous"]

        if ambiguous and reason not in {
            "FORBIDDEN_MERCHANT",
            "MERCHANT_LAUNDERING",
            "SPLIT_TRANSACTION",
        }:
            continue

        if isinstance(reason, str) and isinstance(priority, int):
            candidates.append((priority, item_id, reason))

    candidates.sort(key=lambda x: (x[0], x[1]))
    if candidates:
        _, item_id, reason = candidates[0]
        return {"action_type": "flag_item", "item_id": item_id, "reason_code": reason}

    for item in observation.get("line_items", []):
        item_id = item["item_id"]
        if item_id in processed_ids:
            continue
        if signals[item_id]["reason"] is None and not signals[item_id]["ambiguous"]:
            return {"action_type": "approve_item", "item_id": item_id}

    decision = "partial_reject" if flagged_ids else "approve"
    return {"action_type": "set_batch_decision", "decision": decision}


def main() -> None:
    all_rewards: list[str] = []
    total_steps = 0
    overall_success = True

    try:
        _wait_for_server()
        # _call_llm_once()

        task_files = _get_all_task_files()

        for task_file in task_files:
            rewards: list[str] = []
            steps = 0
            task_id = "unknown"

            try:
                os.environ["AUDITGUARD_TASK_FILE"] = task_file

                obs_payload = _reset_with_optional_forced_task()
                obs = obs_payload["observation"]
                task_id = obs.get("task_id", "unknown")
                print(f"[START] task={task_id} env=auditguard model=dummy", flush=True)
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

                    if reward <= 0.0:
                        reward = 0.01
                    elif reward >= 1.0:
                        reward = 0.99

                    rewards.append(_format_reward(reward))

                    print(
                        f"[STEP] step={steps} action={action_label} "
                        f"reward={_format_reward(reward)} done={_format_done(done)} error={_format_error(error)}",
                        flush=True
                    )

                task_score = sum(float(r) for r in rewards) / max(1, len(rewards))
                task_score = max(0.011, min(0.989, task_score))

                print(f"[END] task={task_id} score={format(task_score, '.2f')} steps={steps}", flush=True)

            except Exception as task_exc:
                print(f"[ERROR] task={task_id} error={task_exc}", flush=True)
                overall_success = False

            finally:
                all_rewards.extend(rewards)
                total_steps += steps

    except Exception as exc:
        print(f"FATAL: {exc}", flush=True)
        overall_success = False

    finally:
        final_score = sum(float(r) for r in all_rewards) / max(1, len(all_rewards))
        final_score = max(0.011, min(0.989, final_score))

        # print(json.dumps({
        #     "task_id": "overall",
        #     "score": float(final_score)
        # }), flush=True)

        print(
            f"[END] success={_format_done(overall_success)} steps={total_steps} rewards={','.join(all_rewards)}",
            flush=True
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("[END] success=false steps=0 rewards=", flush=True)