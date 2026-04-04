from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ServiceHealth(str, Enum):
    up = "up"
    down = "down"
    degraded = "degraded"


class ActionType(str, Enum):
    classify_incident = "classify_incident"
    set_priority = "set_priority"
    propose_fix = "propose_fix"
    execute_fix = "execute_fix"
    escalate = "escalate"
    resolve = "resolve"


class Alert(BaseModel):
    source: str
    name: str
    severity: str
    message: str


class ActionHistoryItem(BaseModel):
    step: int
    type: ActionType
    incident_id: str
    content: Optional[str] = None
    outcome: str


class Observation(BaseModel):
    alerts: List[Alert]
    logs: List[str]
    services_status: Dict[str, ServiceHealth]
    current_incident_id: str
    action_history: List[ActionHistoryItem] = Field(default_factory=list)
    task_id: str
    task_difficulty: Literal["easy", "medium", "hard"]
    incident_summary: str
    resolved: bool = False


class Action(BaseModel):
    type: ActionType
    incident_id: str
    content: Optional[str] = None

    @model_validator(mode="after")
    def strip_content(self) -> "Action":
        if self.content is not None:
            self.content = self.content.strip() or None
        return self


class Reward(BaseModel):
    value: float = Field(ge=0.0, le=1.0)
    breakdown: Dict[str, float] = Field(default_factory=dict)
    reason: str


class IncidentTask(BaseModel):
    task_id: str
    title: str
    difficulty: Literal["easy", "medium", "hard"]
    incident_id: str
    incident_summary: str
    alerts: List[Alert]
    logs: List[str]
    services_status: Dict[str, ServiceHealth]
    expected_classification: str
    expected_priority: Optional[str] = None
    root_cause_aliases: List[List[str]] = Field(default_factory=list)
    fix_aliases: List[List[str]] = Field(default_factory=list)
    execution_aliases: List[List[str]] = Field(default_factory=list)
    recommended_escalation: Optional[str] = None
    component_weights: Dict[str, float]
    max_steps: int = 8

    @model_validator(mode="after")
    def validate_weights(self) -> "IncidentTask":
        total = sum(self.component_weights.values())
        if total <= 0:
            raise ValueError("component_weights must sum to a positive value")
        if abs(total - 1.0) > 1e-9:
            raise ValueError("component_weights must sum to exactly 1.0")
        return self


class IncidentMemory(BaseModel):
    task_id: str
    incident_id: str
    step_count: int = 0
    classification: Optional[str] = None
    priority: Optional[str] = None
    root_cause: Optional[str] = None
    proposed_fix: Optional[str] = None
    executed_fix: Optional[str] = None
    escalated_to: Optional[str] = None
    resolved: bool = False
    component_scores: Dict[str, float] = Field(default_factory=dict)
    penalty_points: float = 0.0
    action_history: List[ActionHistoryItem] = Field(default_factory=list)


class ResetRequest(BaseModel):
    task_id: Optional[str] = None


class StepResponse(BaseModel):
    observation: Observation
    reward: Reward
    done: bool
    info: Dict[str, Any]
