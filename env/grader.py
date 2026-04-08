from __future__ import annotations

import re
from typing import Dict, List

from env.models import Action, ActionType, IncidentMemory, IncidentTask, Reward


class IncidentGrader:
    """Deterministic keyword-based grader for incident handling actions."""

    SCORE_EPSILON = 0.01
    INCIDENT_MISMATCH_PENALTY = 0.15
    WRONG_ACTION_PENALTY = 0.10
    DUPLICATE_ACTION_PENALTY = 0.02
    EARLY_RESOLVE_PENALTY = 0.12
    EMPTY_CONTENT_PENALTY = 0.08

    CLASSIFICATION_ALIASES = {
        "network": "network",
        "networking": "network",
        "router": "network",
        "switch": "network",
        "wan": "network",
        "server": "server",
        "host": "server",
        "vm": "server",
        "compute": "server",
        "db": "db",
        "database": "db",
        "postgres": "db",
        "mysql": "db",
        "security": "security",
        "sec": "security",
        "malware": "security",
        "intrusion": "security",
    }

    PRIORITY_ALIASES = {
        "p1": "P1",
        "sev1": "P1",
        "critical": "P1",
        "urgent": "P1",
        "p2": "P2",
        "sev2": "P2",
        "high": "P2",
        "major": "P2",
        "p3": "P3",
        "sev3": "P3",
        "medium": "P3",
        "moderate": "P3",
        "p4": "P4",
        "sev4": "P4",
        "low": "P4",
        "minor": "P4",
    }

    def apply_action(self, task: IncidentTask, memory: IncidentMemory, action: Action) -> Reward:
        breakdown: Dict[str, float] = {}
        messages: List[str] = []
        reward_value = 0.0

        if action.incident_id != task.incident_id:
            memory.penalty_points += self.INCIDENT_MISMATCH_PENALTY
            return Reward(
                value=0.0,
                breakdown={"incident_id": -self.INCIDENT_MISMATCH_PENALTY},
                reason="Action incident_id does not match the active incident.",
            )

        content = (action.content or "").strip()
        if action.type in {
            ActionType.classify_incident,
            ActionType.set_priority,
            ActionType.propose_fix,
            ActionType.execute_fix,
            ActionType.escalate,
        } and not content:
            memory.penalty_points += self.EMPTY_CONTENT_PENALTY
            return Reward(
                value=0.0,
                breakdown={"content": -self.EMPTY_CONTENT_PENALTY},
                reason=f"{action.type.value} requires a non-empty content field.",
            )

        if action.type == ActionType.classify_incident:
            normalized = self.normalize_classification(content)
            memory.classification = normalized
            if "classification" not in task.component_weights:
                return Reward(
                    value=0.0,
                    breakdown={},
                    reason="Classification noted, but this task scores other objectives.",
                )
            if "classification" in memory.component_scores:
                return self._duplicate_reward(memory, "classification", "Classification already awarded.")
            if normalized == task.expected_classification:
                reward_value += self._award_component(task, memory, "classification", breakdown)
                messages.append(f"Correctly classified the incident as {normalized}.")
            else:
                self._penalize(memory, breakdown, "classification")
                messages.append("Incorrect incident classification.")

        elif action.type == ActionType.set_priority:
            normalized = self.normalize_priority(content)
            memory.priority = normalized
            if "priority" not in task.component_weights:
                return Reward(
                    value=0.0,
                    breakdown={},
                    reason="Priority recorded, but this task does not score priority directly.",
                )
            if "priority" in memory.component_scores:
                return self._duplicate_reward(memory, "priority", "Priority already awarded.")
            if normalized == task.expected_priority:
                reward_value += self._award_component(task, memory, "priority", breakdown)
                messages.append(f"Priority set correctly to {normalized}.")
            else:
                self._penalize(memory, breakdown, "priority")
                messages.append("Incorrect incident priority.")

        elif action.type == ActionType.propose_fix:
            parsed = self.parse_content(content)
            root_cause_text = parsed.get("root_cause", content)
            fix_text = parsed.get("fix", content)
            memory.root_cause = root_cause_text
            memory.proposed_fix = fix_text

            if "root_cause" in task.component_weights:
                if "root_cause" in memory.component_scores:
                    self._apply_duplicate_penalty(memory, breakdown, "root_cause")
                    messages.append("Root cause already captured.")
                elif self.matches_aliases(root_cause_text, task.root_cause_aliases):
                    reward_value += self._award_component(task, memory, "root_cause", breakdown)
                    messages.append("Root cause identified correctly from the logs.")
                else:
                    self._penalize(memory, breakdown, "root_cause")
                    messages.append("Root cause did not match the incident evidence.")

            if "fix_proposal" in task.component_weights:
                if "fix_proposal" in memory.component_scores:
                    self._apply_duplicate_penalty(memory, breakdown, "fix_proposal")
                    messages.append("Fix proposal already captured.")
                elif self.matches_aliases(fix_text, task.fix_aliases):
                    reward_value += self._award_component(task, memory, "fix_proposal", breakdown)
                    messages.append("Remediation plan is appropriate for the incident.")
                else:
                    self._penalize(memory, breakdown, "fix_proposal")
                    messages.append("Remediation plan is incomplete or incorrect.")

            if not messages:
                messages.append("Fix proposal recorded with no score impact for this task.")

        elif action.type == ActionType.execute_fix:
            memory.executed_fix = content
            if "fix_execution" not in task.component_weights:
                return Reward(
                    value=0.0,
                    breakdown={},
                    reason="Execution recorded, but this task does not score fix execution.",
                )
            if "fix_execution" in memory.component_scores:
                return self._duplicate_reward(memory, "fix_execution", "Fix execution already awarded.")
            if self.matches_aliases(content, task.execution_aliases or task.fix_aliases):
                reward_value += self._award_component(task, memory, "fix_execution", breakdown)
                messages.append("Fix execution matches the expected remediation action.")
            else:
                self._penalize(memory, breakdown, "fix_execution")
                messages.append("Executed remediation does not address the incident.")

        elif action.type == ActionType.escalate:
            memory.escalated_to = content
            if task.recommended_escalation:
                expected = self.normalize_text(task.recommended_escalation)
                actual = self.normalize_text(content)
                if expected and expected in actual:
                    messages.append(f"Escalated correctly to {task.recommended_escalation}.")
                else:
                    messages.append(
                        f"Escalation recorded. Preferred target for this incident is {task.recommended_escalation}."
                    )
            else:
                messages.append("Escalation recorded.")

        elif action.type == ActionType.resolve:
            unresolved = [
                component
                for component in self.required_components_before_resolution(task)
                if component not in memory.component_scores
            ]
            if unresolved:
                memory.penalty_points += self.EARLY_RESOLVE_PENALTY
                return Reward(
                    value=0.0,
                    breakdown={"resolution": -self.EARLY_RESOLVE_PENALTY},
                    reason=f"Incident cannot be resolved yet. Missing: {', '.join(unresolved)}.",
                )
            memory.resolved = True
            if "resolution" in task.component_weights:
                if "resolution" in memory.component_scores:
                    return self._duplicate_reward(memory, "resolution", "Incident is already resolved.")
                reward_value += self._award_component(task, memory, "resolution", breakdown)
                messages.append("Incident resolved after all required remediation steps.")
            else:
                messages.append("Incident marked resolved.")

        return Reward(
            value=round(reward_value, 4),
            breakdown={key: round(value, 4) for key, value in breakdown.items()},
            reason=" ".join(messages) if messages else "Action processed.",
        )

    def score(self, task: IncidentTask, memory: IncidentMemory) -> float:
        raw_score = sum(memory.component_scores.values()) - memory.penalty_points
        clamped_score = max(0.0, min(1.0, raw_score))
        if clamped_score <= 0.0:
            return self.SCORE_EPSILON
        if clamped_score >= 1.0:
            return round(1.0 - self.SCORE_EPSILON, 4)
        return round(clamped_score, 4)

    def missing_components(self, task: IncidentTask, memory: IncidentMemory) -> list[str]:
        return [
            component
            for component in task.component_weights
            if component not in memory.component_scores
        ]

    def is_complete(self, task: IncidentTask, memory: IncidentMemory) -> bool:
        for component in task.component_weights:
            if component not in memory.component_scores:
                return False
        if "resolution" in task.component_weights and not memory.resolved:
            return False
        return True

    def required_components_before_resolution(self, task: IncidentTask) -> list[str]:
        return [
            component
            for component in task.component_weights
            if component != "resolution"
        ]

    def normalize_classification(self, content: str) -> str:
        normalized = self.normalize_text(content)
        for alias, canonical in self.CLASSIFICATION_ALIASES.items():
            if alias in normalized:
                return canonical
        return normalized

    def normalize_priority(self, content: str) -> str:
        normalized = self.normalize_text(content)
        for alias, canonical in self.PRIORITY_ALIASES.items():
            if alias in normalized:
                return canonical
        return normalized.upper()

    def matches_aliases(self, candidate: str, aliases: list[list[str]]) -> bool:
        normalized_candidate = self.normalize_text(candidate)
        for alias_group in aliases:
            if all(self.normalize_text(alias) in normalized_candidate for alias in alias_group):
                return True
        return False

    def parse_content(self, content: str) -> dict[str, str]:
        entries: dict[str, str] = {}
        for part in re.split(r"[;\n]+", content):
            item = part.strip()
            if not item:
                continue
            separator = "=" if "=" in item else ":" if ":" in item else None
            if not separator:
                continue
            key, value = item.split(separator, 1)
            normalized_key = self.normalize_text(key).replace(" ", "_")
            entries[normalized_key] = value.strip()
        return entries

    def normalize_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()

    def _award_component(
        self,
        task: IncidentTask,
        memory: IncidentMemory,
        component: str,
        breakdown: dict[str, float],
    ) -> float:
        weight = task.component_weights[component]
        memory.component_scores[component] = weight
        breakdown[component] = weight
        return weight

    def _penalize(
        self,
        memory: IncidentMemory,
        breakdown: dict[str, float],
        component: str,
        penalty: float | None = None,
    ) -> float:
        applied_penalty = penalty if penalty is not None else self.WRONG_ACTION_PENALTY
        memory.penalty_points += applied_penalty
        breakdown[f"{component}_penalty"] = -applied_penalty
        return applied_penalty

    def _apply_duplicate_penalty(
        self,
        memory: IncidentMemory,
        breakdown: dict[str, float],
        component: str,
    ) -> float:
        memory.penalty_points += self.DUPLICATE_ACTION_PENALTY
        breakdown[f"{component}_duplicate"] = -self.DUPLICATE_ACTION_PENALTY
        return self.DUPLICATE_ACTION_PENALTY

    def _duplicate_reward(self, memory: IncidentMemory, component: str, message: str) -> Reward:
        memory.penalty_points += self.DUPLICATE_ACTION_PENALTY
        return Reward(
            value=0.0,
            breakdown={f"{component}_duplicate": -self.DUPLICATE_ACTION_PENALTY},
            reason=message,
        )
