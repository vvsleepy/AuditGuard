🔥 AUDITGUARD — FINAL WINNING BLUEPRINT (CODEX-LOCKED SPEC)

SYSTEM OVERVIEW
AuditGuard is an OpenEnv-compatible environment where:
- Each episode = one audit case
- Agent performs step-by-step auditing
- Uses:
    - policy rules
    - expense data
    - fraud patterns
- Must:
    - flag violations
    - approve clean items
    - request info when needed
    - finalize batch decision

STRICT INTERFACE SPEC

RESET API
POST /reset

Response:
{
  "observation": { ... },
  "info": {}
}

STEP API
POST /step

Request:
{
  "action": {
    "action_type": "flag_item",
    "item_id": "item_3",
    "reason_code": "OVER_POLICY_CAP"
  }
}

STEP RESPONSE
{
  "observation": { ... },
  "reward": 0.12,
  "done": false,
  "info": {
    "error": null
  }
}

ACTION ENUM (FIXED)
flag_item
approve_item
request_info
set_batch_decision
finalize

REASON CODES (FIXED)
MISSING_RECEIPT
OVER_POLICY_CAP
FORBIDDEN_MERCHANT
CATEGORY_MISMATCH
DUPLICATE_EXPENSE
SPLIT_TRANSACTION
MERCHANT_LAUNDERING
MISSING_REQUIRED_FIELD
DATE_OUTSIDE_POLICY
ROUND_AMOUNT_ANOMALY

OBSERVATION STRUCTURE (DO NOT CHANGE)
{
  "task_id": "easy_001",
  "difficulty": "easy",
  "company_policy": {...},
  "line_items": [...],
  "receipt_metadata": [...],
  "already_flagged": [...],
  "already_approved": [...],
  "requests_sent": [...],
  "remaining_audit_budget": 6,
  "risk_summary": {...},
  "allowed_actions": [...],
  "last_action_result": {...},
  "step_count": 1,
  "max_steps": 8,
  "done": false
}

TASK SPEC
Each task must include:
- policy
- line_items
- ground_truth

GRADER FORMULA
precision = correct_flags / total_flags
recall = correct_flags / total_true
f1 = 2 * (precision * recall) / (precision + recall)

score =
0.35 * f1 +
0.15 * approval_accuracy +
0.10 * request_quality +
0.25 * final_decision +
0.10 * fraud_bonus +
0.05 * budget_efficiency

Clamp:
score = min(1.0, max(0.0, score))

REWARD SHAPING

Positive:
+0.12 correct flag
+0.06 correct approve
+0.05 useful request
+0.10 fraud cluster detection
+0.20 correct final decision

Negative:
-0.10 false flag
-0.15 wrong approval
-0.04 useless request
-0.05 early finalize
-0.02 extra steps

ENVIRONMENT LOGIC

reset():
- load random task
- initialize state
- return observation

step(action):
- validate action
- update state
- compute reward
- check done
- return response

DONE CONDITIONS
- finalize called
- step_count >= max_steps