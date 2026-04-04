from __future__ import annotations

from typing import Any, Optional

from env.grader import IncidentGrader
from env.models import (
    Action,
    ActionHistoryItem,
    IncidentMemory,
    Observation,
    ResetRequest,
    Reward,
    StepResponse,
)
from env.tasks import TASK_ORDER, get_task

try:
    from fastapi import FastAPI, HTTPException
except ImportError:  # pragma: no cover - optional for non-API local use
    FastAPI = None
    HTTPException = None


class NetworkIncidentTriageEnvironment:
    """Deterministic OpenEnv-compatible environment for NOC incident triage."""

    def __init__(self) -> None:
        self._grader = IncidentGrader()
        self._task_cursor = 0
        self._task = get_task(TASK_ORDER[0])
        self._memory = IncidentMemory(
            task_id=self._task.task_id,
            incident_id=self._task.incident_id,
        )

    def reset(self, task_id: Optional[str] = None) -> Observation:
        if task_id is None:
            selected_task = get_task(TASK_ORDER[self._task_cursor])
            self._task_cursor = (self._task_cursor + 1) % len(TASK_ORDER)
        else:
            selected_task = get_task(task_id)
        self._task = selected_task
        self._memory = IncidentMemory(
            task_id=self._task.task_id,
            incident_id=self._task.incident_id,
        )
        return self.state()

    def step(self, action: Action) -> tuple[Observation, Reward, bool, dict]:
        self._memory.step_count += 1
        reward = self._grader.apply_action(self._task, self._memory, action)
        self._memory.action_history.append(
            ActionHistoryItem(
                step=self._memory.step_count,
                type=action.type,
                incident_id=action.incident_id,
                content=action.content,
                outcome=reward.reason,
            )
        )

        done = self._grader.is_complete(self._task, self._memory)
        max_steps_reached = self._memory.step_count >= self._task.max_steps
        if max_steps_reached:
            done = True

        observation = self.state()
        info = {
            "task_id": self._task.task_id,
            "difficulty": self._task.difficulty,
            "score": self._grader.score(self._task, self._memory),
            "missing_components": self._grader.missing_components(self._task, self._memory),
            "step_count": self._memory.step_count,
            "max_steps": self._task.max_steps,
            "max_steps_reached": max_steps_reached,
            "resolved": self._memory.resolved,
        }
        return observation, reward, done, info

    def state(self) -> Observation:
        return Observation(
            alerts=self._task.alerts,
            logs=self._task.logs,
            services_status=self._task.services_status,
            current_incident_id=self._task.incident_id,
            action_history=self._memory.action_history,
            task_id=self._task.task_id,
            task_difficulty=self._task.difficulty,
            incident_summary=self._task.incident_summary,
            resolved=self._memory.resolved,
        )

    def close(self) -> None:
        return None

ENVIRONMENT = NetworkIncidentTriageEnvironment()
app = None

if FastAPI is not None:
    app = FastAPI(
        title="Network Incident Triage & Remediation",
        version="1.0.0",
        description="Deterministic OpenEnv-compatible NOC incident simulation.",
    )

    @app.post("/reset", response_model=Observation)
    def reset_environment(request: ResetRequest | None = None) -> Observation:
        try:
            return ENVIRONMENT.reset(task_id=request.task_id if request else None)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/")
    def healthcheck() -> dict[str, Any]:
        return {
            "status": "ok",
            "environment": "network-incident-triage-remediation",
            "current_task_id": ENVIRONMENT.state().task_id,
        }

    @app.post("/step", response_model=StepResponse)
    def step_environment(action: Action) -> StepResponse:
        observation, reward, done, info = ENVIRONMENT.step(action)
        return StepResponse(
            observation=observation,
            reward=reward,
            done=done,
            info=info,
        )

    @app.get("/state", response_model=Observation)
    def get_state() -> Observation:
        return ENVIRONMENT.state()
