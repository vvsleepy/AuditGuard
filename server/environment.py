import json
import random
from pathlib import Path
from typing import Any

try:
    from ..models import (
        ActionType,
        AuditGuardAction,
        AuditGuardObservation,
        AuditGuardState,
        AuditTask,
        ReasonCode,
        StepInfo,
    )
except ImportError:
    from models import (  # type: ignore
        ActionType,
        AuditGuardAction,
        AuditGuardObservation,
        AuditGuardState,
        AuditTask,
        ReasonCode,
        StepInfo,
    )


class AuditGuardEnvironment:
    def __init__(self, data_dir: str | Path | None = None, max_steps: int = 8) -> None:
        base_dir = Path(__file__).resolve().parents[1]
        self.data_dir = Path(data_dir) if data_dir is not None else base_dir / "data"
        self.default_max_steps = max_steps
        self.action_costs = {
            "flag_item": 1,
            "approve_item": 1,
            "request_info": 2,
            "set_batch_decision": 0,
            "finalize": 0,
        }
        self.state = AuditGuardState()
        self.current_task: AuditTask | None = None
        self.receipt_metadata: list[dict[str, Any]] = []
        self.flagged_items: list[dict[str, Any]] = []
        self.approved_items: list[str] = []
        self.requests_sent: list[dict[str, Any]] = []
        self.batch_decision: str | None = None
        self.last_action_result: dict[str, Any] = {}
        self.remaining_budget = 0

    def reset(self) -> dict[str, Any]:
        task = self._load_random_task()
        self.current_task = task
        self.receipt_metadata = self._extract_receipt_metadata(task)
        self.flagged_items = []
        self.approved_items = []
        self.requests_sent = []
        self.batch_decision = None
        self.last_action_result = {}
        self.remaining_budget = self._initial_budget(task.difficulty)
        self.state = AuditGuardState(
            task_id=task.task_id,
            step_count=0,
            max_steps=max(self.default_max_steps, len(task.line_items) + 2),
            done=False,
        )
        return self._build_observation()

    def step(self, action: dict[str, Any] | AuditGuardAction) -> tuple[dict[str, Any], float, bool, dict[str, Any]]:
        if self.current_task is None:
            observation = self.reset()
            return observation, 0.0, False, StepInfo(error="Environment was not reset.").model_dump()

        parsed_action, error = self._validate_action(action)
        reward = 0.0

        if error is None:
            action_cost = self.action_costs.get(parsed_action.action_type.value, 0)
            self.remaining_budget = max(self.remaining_budget - action_cost, 0)
            reward = self._apply_action(parsed_action)
            self.last_action_result = {
                "action_type": parsed_action.action_type.value,
                "item_id": parsed_action.item_id,
                "status": "ok",
            }
        else:
            self.last_action_result = {
                "action_type": None,
                "item_id": None,
                "status": "error",
                "error": error,
            }

        self.state.step_count += 1

        if not self.state.done and self.remaining_budget <= 0:
            self.state.done = True

        if not self.state.done and self.state.step_count >= self.state.max_steps:
            self.state.done = True
            if error is None:
                reward -= 0.02

        observation = self._build_observation()
        info = StepInfo(error=error).model_dump()
        return observation, reward, self.state.done, info

    def _load_random_task(self) -> AuditTask:
        task_files = sorted(self.data_dir.glob("*.json"))
        if not task_files:
            raise FileNotFoundError(f"No task files found in {self.data_dir}")

        task_path = random.choice(task_files)
        with task_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return AuditTask.model_validate(payload)

    def _extract_receipt_metadata(self, task: AuditTask) -> list[dict[str, Any]]:
        task_path = self.data_dir / f"{task.task_id}.json"
        if task_path.exists():
            with task_path.open("r", encoding="utf-8") as handle:
                raw_payload = json.load(handle)
            receipt_metadata = raw_payload.get("receipt_metadata")
            if isinstance(receipt_metadata, list):
                return receipt_metadata

        return [
            {
                "item_id": item.item_id,
                "receipt_present": item.receipt_attached,
            }
            for item in task.line_items
        ]

    def _validate_action(
        self, action: dict[str, Any] | AuditGuardAction
    ) -> tuple[AuditGuardAction | None, str | None]:
        if self.state.done:
            return None, "Episode is already done."

        try:
            parsed_action = (
                action if isinstance(action, AuditGuardAction) else AuditGuardAction.model_validate(action)
            )
        except Exception as exc:
            return None, f"Invalid action: {exc}"

        item_id = parsed_action.item_id
        item_ids = {item.item_id for item in self.current_task.line_items} if self.current_task else set()

        if parsed_action.action_type in {
            ActionType.flag_item,
            ActionType.approve_item,
            ActionType.request_info,
        }:
            if not item_id:
                return None, "item_id is required for this action."
            if item_id not in item_ids:
                return None, f"Unknown item_id: {item_id}"

        if parsed_action.action_type == ActionType.flag_item and parsed_action.reason_code is None:
            return None, "reason_code is required for flag_item."

        if parsed_action.action_type == ActionType.request_info and not parsed_action.question:
            return None, "question is required for request_info."

        if parsed_action.action_type == ActionType.set_batch_decision and not parsed_action.decision:
            return None, "decision is required for set_batch_decision."

        return parsed_action, None

    def _apply_action(self, action: AuditGuardAction) -> float:
        assert self.current_task is not None

        if action.action_type == ActionType.flag_item:
            return self._handle_flag(action.item_id, action.reason_code)
        if action.action_type == ActionType.approve_item:
            return self._handle_approve(action.item_id)
        if action.action_type == ActionType.request_info:
            return self._handle_request_info(action.item_id, action.question)
        if action.action_type == ActionType.set_batch_decision:
            self.batch_decision = action.decision
            self.last_action_result = {
                "action_type": action.action_type.value,
                "decision": action.decision,
                "status": "ok",
            }
            return 0.0
        if action.action_type == ActionType.finalize:
            self.state.done = True
            return self._handle_finalize()
        return 0.0

    def _handle_flag(self, item_id: str | None, reason_code: ReasonCode | None) -> float:
        assert self.current_task is not None
        assert item_id is not None
        assert reason_code is not None

        if any(entry["item_id"] == item_id for entry in self.flagged_items):
            self.last_action_result = {
                "action_type": ActionType.flag_item.value,
                "item_id": item_id,
                "status": "duplicate_action",
            }
            return -0.02

        self.flagged_items.append({"item_id": item_id, "reason": reason_code.value})
        violation_map = {
            violation.item_id: violation.reason.value for violation in self.current_task.ground_truth.violations
        }
        reward = 0.12 if violation_map.get(item_id) == reason_code.value else -0.10

        if self._has_fraud_cluster_bonus():
            reward += 0.10

        total_items = len(self.current_task.line_items)
        if total_items and len(self.flagged_items) > total_items * 0.6:
            reward -= 0.10

        return reward

    def _handle_approve(self, item_id: str | None) -> float:
        assert self.current_task is not None
        assert item_id is not None

        if item_id in self.approved_items:
            self.last_action_result = {
                "action_type": ActionType.approve_item.value,
                "item_id": item_id,
                "status": "duplicate_action",
            }
            return -0.02

        self.approved_items.append(item_id)
        if item_id in self.current_task.ground_truth.clean_items:
            return 0.06
        return -0.15

    def _handle_request_info(self, item_id: str | None, question: str | None) -> float:
        assert self.current_task is not None
        assert item_id is not None
        assert question is not None

        self.requests_sent.append(
            {
                "item_id": item_id,
                "question": question,
            }
        )
        item = next(line_item for line_item in self.current_task.line_items if line_item.item_id == item_id)
        description = (item.description or "").lower()
        is_useful = (not item.receipt_attached) or ("unclear" in description) or ("not specified" in description)
        return 0.05 if is_useful else -0.04

    def _handle_finalize(self) -> float:
        assert self.current_task is not None

        reward = 0.0
        if self.state.step_count < 2:
            reward -= 0.05

        if self.batch_decision is None:
            return reward - 0.05
        if self.batch_decision == self.current_task.ground_truth.final_decision:
            return reward + 0.20
        return reward - 0.05

    def _build_observation(self) -> dict[str, Any]:
        if self.current_task is None:
            raise RuntimeError("Environment has no active task.")

        observation = AuditGuardObservation(
            task_id=self.current_task.task_id,
            difficulty=self.current_task.difficulty,
            company_policy=self.current_task.policy.model_dump(),
            line_items=[item.model_dump() for item in self.current_task.line_items],
            receipt_metadata=self.receipt_metadata,
            already_flagged=list(self.flagged_items),
            already_approved=list(self.approved_items),
            requests_sent=list(self.requests_sent),
            remaining_audit_budget=self.remaining_budget,
            risk_summary=self._build_risk_summary(),
            allowed_actions=self._allowed_actions(),
            last_action_result=dict(self.last_action_result),
            step_count=self.state.step_count,
            max_steps=self.state.max_steps,
            done=self.state.done,
        )
        return observation.model_dump()

    def _allowed_actions(self) -> list[str]:
        if self.state.done:
            return []
        return [action.value for action in ActionType]

    def _build_risk_summary(self) -> dict[str, Any]:
        assert self.current_task is not None

        missing_receipts = sum(1 for item in self.current_task.line_items if not item.receipt_attached)
        near_cap_items = 0
        if self.current_task.policy.meal_cap is not None:
            near_cap_items = sum(
                1
                for item in self.current_task.line_items
                if item.category == "meal" and item.amount >= self.current_task.policy.meal_cap * 0.9
            )

        return {
            "flagged_count": len(self.flagged_items),
            "approved_count": len(self.approved_items),
            "requests_count": len(self.requests_sent),
            "missing_receipt_items": missing_receipts,
            "near_policy_cap_items": near_cap_items,
        }

    def _initial_budget(self, difficulty: str) -> int:
        budgets = {
            "easy": 6,
            "medium": 8,
            "hard": 10,
        }
        return budgets.get(difficulty, 8)

    def _has_fraud_cluster_bonus(self) -> bool:
        if self.current_task is None or not self.flagged_items:
            return False

        item_lookup = {item.item_id: item for item in self.current_task.line_items}
        merchant_counts: dict[str, int] = {}

        for flagged in self.flagged_items:
            item = item_lookup.get(flagged["item_id"])
            merchant = item.merchant if item and item.merchant else None
            if merchant is None:
                continue
            merchant_counts[merchant] = merchant_counts.get(merchant, 0) + 1
            if merchant_counts[merchant] >= 2:
                return True

        return len(self.flagged_items) >= 3
