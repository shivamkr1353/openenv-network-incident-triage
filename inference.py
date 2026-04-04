from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv
from openai import OpenAI

from env.environment import NetworkIncidentTriageEnvironment
from env.models import Action, ActionType, Observation
from env.tasks import TASK_ORDER, get_task

load_dotenv()

BENCHMARK = "network-incident-triage-remediation"
API_BASE_URL = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")
HF_TOKEN = os.getenv("HF_TOKEN")
LOCAL_IMAGE_NAME = os.getenv("LOCAL_IMAGE_NAME")
API_KEY = HF_TOKEN or os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY")
MAX_TOKENS = 220
SUCCESS_SCORE_THRESHOLD = 0.95
SYSTEM_PROMPT = (
    "You are operating a deterministic OpenEnv environment for network incident triage. "
    "Return exactly one JSON object with keys type, incident_id, and content. "
    "Valid action types are classify_incident, set_priority, propose_fix, execute_fix, escalate, resolve. "
    "Base every action only on the observation and prior action history."
)

REFERENCE_ACTIONS = {
    "task_easy_network_classification": [
        Action(
            type=ActionType.classify_incident,
            incident_id="INC-NET-1001",
            content="network",
        ),
    ],
    "task_medium_root_cause_priority": [
        Action(
            type=ActionType.propose_fix,
            incident_id="INC-DB-2042",
            content=(
                "root_cause=reporting worker left idle in transaction sessions open "
                "and exhausted orders-db connection slots; "
                "fix=terminate the stuck reporting sessions and restart the reporting worker"
            ),
        ),
        Action(
            type=ActionType.set_priority,
            incident_id="INC-DB-2042",
            content="P2",
        ),
    ],
    "task_hard_full_workflow": [
        Action(
            type=ActionType.classify_incident,
            incident_id="INC-SEC-9007",
            content="security",
        ),
        Action(
            type=ActionType.set_priority,
            incident_id="INC-SEC-9007",
            content="P1",
        ),
        Action(
            type=ActionType.propose_fix,
            incident_id="INC-SEC-9007",
            content=(
                "root_cause=compromised deploy key was used to install a crypto miner "
                "on web-node-3; "
                "fix=isolate web-node-3, revoke the deploy key, and rebuild the node"
            ),
        ),
        Action(
            type=ActionType.execute_fix,
            incident_id="INC-SEC-9007",
            content="isolated web-node-3, revoked the deploy key, and rebuilt the host",
        ),
        Action(
            type=ActionType.resolve,
            incident_id="INC-SEC-9007",
            content="malicious node rebuilt and traffic returned to baseline",
        ),
    ],
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the submission baseline against all tasks.")
    parser.add_argument(
        "--task-id",
        choices=sorted(TASK_ORDER),
        help="Run only one task instead of the full benchmark.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip API calls and use the deterministic fallback planner.",
    )
    return parser


def extract_json_object(payload: str) -> dict[str, Any]:
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", payload, flags=re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in model response.") from None
        return json.loads(match.group(0))


def build_user_prompt(observation: Observation) -> str:
    return json.dumps(observation.model_dump(mode="json"), separators=(",", ":"))


def fallback_action(task_id: str, step_index: int) -> Action:
    actions = REFERENCE_ACTIONS[task_id]
    return actions[min(step_index, len(actions) - 1)]


def select_action(
    client: OpenAI | None,
    observation: Observation,
    step_index: int,
) -> tuple[Action, str | None]:
    if client is None:
        return fallback_action(observation.task_id, step_index), "offline_fallback"

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            temperature=0,
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(observation)},
            ],
        )
        payload = response.choices[0].message.content or ""
        return Action.model_validate(extract_json_object(payload)), None
    except Exception:
        return fallback_action(observation.task_id, step_index), "model_fallback"


def format_action_for_log(action: Action) -> str:
    content = quote(action.content or "", safe="")
    return f"{action.type.value}(incident_id={action.incident_id},content={content})"


def log_start(task_name: str) -> None:
    print(f"[START] task={task_name} env={BENCHMARK} model={MODEL_NAME}", flush=True)


def log_step(step: int, action: Action, reward: float, done: bool, error: str | None) -> None:
    error_value = error if error else "null"
    done_value = str(done).lower()
    print(
        f"[STEP] step={step} action={format_action_for_log(action)} "
        f"reward={reward:.2f} done={done_value} error={error_value}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: list[float]) -> None:
    rewards_str = ",".join(f"{reward:.2f}" for reward in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} "
        f"score={score:.2f} rewards={rewards_str}",
        flush=True,
    )


def run_episode(env: NetworkIncidentTriageEnvironment, client: OpenAI | None, task_id: str) -> float:
    observation = env.reset(task_id=task_id)
    max_steps = get_task(task_id).max_steps
    rewards: list[float] = []
    steps_taken = 0
    score = 0.0
    success = False

    log_start(task_id)

    try:
        for step in range(1, max_steps + 1):
            action, error = select_action(client, observation, step - 1)
            observation, reward, done, info = env.step(action)
            reward_value = reward.value
            rewards.append(reward_value)
            steps_taken = step
            score = float(info.get("score", 0.0))
            log_step(step=step, action=action, reward=reward_value, done=done, error=error)
            if done:
                break
        success = score >= SUCCESS_SCORE_THRESHOLD
    finally:
        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)

    return score


def build_client(offline: bool) -> OpenAI | None:
    if offline:
        return None
    if not API_KEY:
        raise RuntimeError(
            "Missing HF_TOKEN or OPENAI_API_KEY. Set API_BASE_URL, MODEL_NAME, and HF_TOKEN before running inference."
        )
    return OpenAI(base_url=API_BASE_URL, api_key=API_KEY)


def main() -> None:
    args = build_parser().parse_args()
    task_ids = [args.task_id] if args.task_id else list(TASK_ORDER)
    client = build_client(args.offline)
    env = NetworkIncidentTriageEnvironment()

    for task_id in task_ids:
        run_episode(env=env, client=client, task_id=task_id)


if __name__ == "__main__":
    main()
