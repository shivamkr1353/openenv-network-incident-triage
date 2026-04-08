---
title: Network Incident Triage OpenEnv
colorFrom: blue
colorTo: green
sdk: docker
app_port: 8000
suggested_hardware: cpu-basic
tags:
  - openenv
  - docker
  - fastapi
  - agents
  - sre
short_description: OpenEnv benchmark for network incident triage.
---

# Network Incident Triage and Remediation

This project is a complete OpenEnv environment for a real Network Operations Center workflow. An agent receives alerts, logs, service-health data, and a live incident summary, then must classify the incident, set priority, identify root cause, propose a remediation plan, execute the fix, and resolve the incident.

The environment is designed for practical agent evaluation rather than toy play. It models work that SRE, NOC, and security engineers actually do during infrastructure incidents.

## Why this environment is useful

- Real-world utility: incident response is a high-value workflow for autonomous agents.
- Structured evaluation: every task has a deterministic grader with a normalized score in `[0.0, 1.0]`.
- Dense rewards: agents get partial credit for useful progress and lose final score for bad behavior such as wrong classifications, duplicate work, mismatched incident IDs, or resolving too early.
- Reproducible baselines: the included `inference.py` uses the OpenAI client with deterministic prompts and strict structured logs.

## OpenEnv interface

The environment implements the standard OpenEnv API:

- `reset(task_id: Optional[str] = None) -> Observation`
- `step(action: Action) -> tuple[Observation, Reward, bool, dict]`
- `state() -> Observation`

The HTTP service exposes:

- `GET /` healthcheck, returns `200 OK`
- `POST /reset`
- `POST /step`
- `GET /state`

Typed Pydantic models are defined in `env/models.py`.

## Observation space

`Observation` contains:

- `alerts: List[Alert]`
- `logs: List[str]`
- `services_status: Dict[str, ServiceHealth]`
- `current_incident_id: str`
- `action_history: List[ActionHistoryItem]`
- `task_id: str`
- `task_difficulty: Literal["easy", "medium", "hard"]`
- `incident_summary: str`
- `resolved: bool`

## Action space

`Action` contains:

- `type: ActionType`
- `incident_id: str`
- `content: Optional[str]`

Valid `ActionType` values:

- `classify_incident`
- `set_priority`
- `propose_fix`
- `execute_fix`
- `escalate`
- `resolve`

## Reward design

Step rewards are always normalized to `[0.0, 1.0]`. Final task scores are kept strictly inside `(0.0, 1.0)` to satisfy the hackathon validator. Positive progress is awarded immediately when the agent completes a meaningful part of the workflow. Penalties reduce the final normalized score rather than emitting negative step rewards, which keeps the reward interface within the hackathon constraints.

Penalty cases include:

- wrong `incident_id`
- empty required content
- duplicate component submissions
- resolving before required steps are complete
- incorrect classifications, priorities, diagnoses, or remediations

## Tasks

The benchmark ships with three deterministic tasks:

1. `task_easy_network_classification`
   Goal: classify a packet-loss incident caused by uplink degradation.
   Expected difficulty: easy.
2. `task_medium_root_cause_priority`
   Goal: identify a database connection exhaustion root cause and assign the correct priority.
   Expected difficulty: medium.
3. `task_hard_full_workflow`
   Goal: complete a security-incident workflow from classification through remediation and final resolution.
   Expected difficulty: hard.

Task definitions live in `env/tasks.py`, and grading logic lives in `env/grader.py`.

## Baseline inference

The root-level `inference.py` is submission-ready:

- uses the OpenAI Python client
- reads `API_BASE_URL`, `MODEL_NAME`, and `HF_TOKEN`
- emits strict `[START]`, `[STEP]`, and `[END]` lines only
- runs all three tasks by default
- supports `--task-id` for single-task debugging
- supports `--offline` for local smoke tests without network calls

The script uses deterministic prompts with `temperature=0`. If a model response is malformed, it falls back to a deterministic reference action for that step so the benchmark remains runnable and reproducible.

### Required environment variables

Set these before submission:

- `API_BASE_URL`
- `MODEL_NAME`
- `HF_TOKEN`

For local debugging, `OPENAI_API_KEY` is also accepted as a fallback secret name.

### Expected log format

The script prints exactly these line types:

```text
[START] task=<task_name> env=<benchmark> model=<model_name>
[STEP] step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>
[END] success=<true|false> steps=<n> score=<score> rewards=<r1,r2,...,rn>
```

### Reference scores

The deterministic reference planner reaches:

- Easy: `0.99`
- Medium: `0.99`
- Hard: `0.99`

## Local setup

Install dependencies:

```bash
pip install openenv-core fastapi uvicorn pydantic openai python-dotenv
```

Validate the environment:

```bash
openenv validate
```

Run the API locally:

```bash
python -m server.app
```

Run the submission baseline against all tasks:

```bash
python inference.py
```

Run an offline smoke test without external API calls:

```bash
python inference.py --offline
```

Run the local pre-submit validator:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\validate-submission.ps1 -PingUrl https://your-space.hf.space -RepoDir .
```

If you prefer Bash or CI runners:

```bash
bash ./scripts/validate-submission.sh https://your-space.hf.space .
```

## Docker

Build and run locally:

```bash
docker build -t network-incident-openenv .
docker run -p 8000:8000 network-incident-openenv
```

After startup:

- `GET http://localhost:8000/` returns a `200 OK` health payload.
- `POST http://localhost:8000/reset` returns the initial observation.

## Hugging Face Spaces

This repository is configured as a Docker Space through the YAML front matter at the top of this `README.md`, following the Hugging Face Spaces configuration reference:

- `sdk: docker`
- `app_port: 8000`
- `tags: [openenv, docker, fastapi, agents, sre]`

Source: Hugging Face Spaces Configuration Reference: https://huggingface.co/docs/hub/en/spaces-config-reference

## Project structure

- `env/environment.py`: environment class and FastAPI app
- `env/models.py`: typed OpenEnv models
- `env/tasks.py`: easy, medium, and hard task definitions
- `env/grader.py`: deterministic graders and score shaping
- `server/app.py`: local API entrypoint
- `openenv.yaml`: benchmark metadata
- `Dockerfile`: container runtime

## Submission checklist

- OpenEnv spec implemented with typed models
- `openenv validate` passes
- 3 tasks with deterministic graders
- normalized reward outputs in `[0.0, 1.0]` and task scores strictly inside `(0.0, 1.0)`
- root healthcheck returns `200 OK`
- Docker image builds and serves the API
- baseline inference script is at repo root and uses the OpenAI client
