from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ActionType(str, Enum):
    flag_item = "flag_item"
    approve_item = "approve_item"
    request_info = "request_info"
    set_batch_decision = "set_batch_decision"
    finalize = "finalize"


class ReasonCode(str, Enum):
    MISSING_RECEIPT = "MISSING_RECEIPT"
    OVER_POLICY_CAP = "OVER_POLICY_CAP"
    FORBIDDEN_MERCHANT = "FORBIDDEN_MERCHANT"
    CATEGORY_MISMATCH = "CATEGORY_MISMATCH"
    DUPLICATE_EXPENSE = "DUPLICATE_EXPENSE"
    SPLIT_TRANSACTION = "SPLIT_TRANSACTION"
    MERCHANT_LAUNDERING = "MERCHANT_LAUNDERING"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    DATE_OUTSIDE_POLICY = "DATE_OUTSIDE_POLICY"
    ROUND_AMOUNT_ANOMALY = "ROUND_AMOUNT_ANOMALY"


class LineItem(BaseModel):
    model_config = {"extra": "forbid"}

    item_id: str
    amount: float
    category: str
    receipt_attached: bool
    merchant: str | None = None
    date: str | None = None
    currency: str | None = None
    employee_id: str | None = None
    description: str | None = None


class CompanyPolicy(BaseModel):
    model_config = {"extra": "forbid"}

    meal_cap: float | None = None
    require_receipt_over: float | None = None
    forbidden_merchants: list[str] = Field(default_factory=list)
    allowed_categories: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)


class ViolationRecord(BaseModel):
    model_config = {"extra": "forbid"}

    item_id: str
    reason: ReasonCode


class GroundTruth(BaseModel):
    model_config = {"extra": "forbid"}

    violations: list[ViolationRecord] = Field(default_factory=list)
    clean_items: list[str] = Field(default_factory=list)
    final_decision: str


class AuditTask(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_id: str
    difficulty: str
    policy: CompanyPolicy
    line_items: list[LineItem] = Field(default_factory=list)
    ground_truth: GroundTruth


class AuditGuardAction(BaseModel):
    model_config = {"extra": "forbid"}

    action_type: ActionType
    item_id: str | None = None
    reason_code: ReasonCode | None = None
    question: str | None = None
    decision: str | None = None


class AuditGuardObservation(BaseModel):
    model_config = {"extra": "forbid"}

    task_id: str
    difficulty: str
    company_policy: dict
    line_items: list[dict] = Field(default_factory=list)
    receipt_metadata: list[dict] = Field(default_factory=list)
    already_flagged: list[dict] = Field(default_factory=list)
    already_approved: list[str] = Field(default_factory=list)
    requests_sent: list[dict] = Field(default_factory=list)
    remaining_audit_budget: int
    risk_summary: dict
    allowed_actions: list[str] = Field(default_factory=list)
    last_action_result: dict
    step_count: int
    max_steps: int
    done: bool


class StepInfo(BaseModel):
    model_config = {"extra": "forbid"}

    error: str | None = None


class StepResponse(BaseModel):
    model_config = {"extra": "forbid"}

    observation: AuditGuardObservation
    reward: float
    done: bool
    info: StepInfo


class AuditGuardState(BaseModel):
    model_config = {"extra": "forbid"}

    task_id: str | None = None
    step_count: int = 0
    max_steps: int = 0
    done: bool = False
