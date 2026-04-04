from __future__ import annotations

from env.models import Alert, IncidentTask, ServiceHealth


TASKS = {
    "task_easy_network_classification": IncidentTask(
        task_id="task_easy_network_classification",
        title="Classify a network incident",
        difficulty="easy",
        incident_id="INC-NET-1001",
        incident_summary=(
            "A branch office is reporting intermittent packet loss after the core "
            "switch uplink started throwing CRC errors."
        ),
        alerts=[
            Alert(
                source="nms",
                name="packet-loss-branch-12",
                severity="medium",
                message="Packet loss exceeded 32% on branch-12 WAN path.",
            ),
            Alert(
                source="router-monitor",
                name="bgp-flap-edge-west",
                severity="medium",
                message="BGP neighbor edge-west reset twice in five minutes.",
            ),
        ],
        logs=[
            "sw-core-1 interface xe-0/0/48 CRC errors increased from 4 to 1840 in 90 seconds",
            "edge-west: retransmits rising on uplink bundle ae1 after optical signal degradation",
            "voice-gateway branch-12 jitter climbed to 180ms while core uplink dropped frames",
        ],
        services_status={
            "branch-connectivity": ServiceHealth.degraded,
            "internet-egress": ServiceHealth.degraded,
            "orders-db": ServiceHealth.up,
            "identity-service": ServiceHealth.up,
        },
        expected_classification="network",
        expected_priority="P3",
        root_cause_aliases=[
            ["crc errors", "uplink"],
            ["optical signal", "uplink"],
        ],
        fix_aliases=[
            ["fail over", "uplink"],
            ["replace", "optic"],
        ],
        component_weights={
            "classification": 1.0,
        },
        max_steps=4,
    ),
    "task_medium_root_cause_priority": IncidentTask(
        task_id="task_medium_root_cause_priority",
        title="Find database root cause and set priority",
        difficulty="medium",
        incident_id="INC-DB-2042",
        incident_summary=(
            "Checkout latency is rising because the orders database is running out "
            "of available connections."
        ),
        alerts=[
            Alert(
                source="apm",
                name="checkout-api-p95-latency",
                severity="high",
                message="checkout-api p95 latency exceeded 4.2s for 8 minutes.",
            ),
            Alert(
                source="postgres-exporter",
                name="orders-db-connection-pressure",
                severity="high",
                message="orders-db active connections at 97% of max_connections.",
            ),
        ],
        logs=[
            "postgres: remaining connection slots are reserved for non-replication superuser connections",
            "reporting-worker-2 opened 180 idle in transaction sessions against orders-db",
            "checkout-api connection pool timeout waiting 3000ms for a free postgres client",
        ],
        services_status={
            "checkout-api": ServiceHealth.degraded,
            "orders-db": ServiceHealth.degraded,
            "reporting-worker": ServiceHealth.degraded,
            "edge-router": ServiceHealth.up,
        },
        expected_classification="db",
        expected_priority="P2",
        root_cause_aliases=[
            ["reporting", "idle in transaction", "connection slots"],
            ["reporting worker", "exhausted", "connections"],
            ["reporting", "connection pool", "timeout"],
        ],
        fix_aliases=[
            ["terminate", "reporting", "sessions"],
            ["restart", "reporting", "worker"],
            ["clear", "idle in transaction"],
        ],
        component_weights={
            "root_cause": 0.6,
            "priority": 0.4,
        },
        max_steps=5,
    ),
    "task_hard_full_workflow": IncidentTask(
        task_id="task_hard_full_workflow",
        title="Complete security incident workflow",
        difficulty="hard",
        incident_id="INC-SEC-9007",
        incident_summary=(
            "A public API node is degraded after a compromised deployment credential "
            "was used to install a crypto miner."
        ),
        alerts=[
            Alert(
                source="edr",
                name="malware-suspected-web-node-3",
                severity="critical",
                message="EDR detected xmrig service execution on web-node-3.",
            ),
            Alert(
                source="netflow",
                name="outbound-traffic-anomaly",
                severity="critical",
                message="web-node-3 outbound traffic to mining pool exceeded baseline by 18x.",
            ),
            Alert(
                source="infra-monitor",
                name="public-api-error-rate",
                severity="high",
                message="public-api 5xx error rate above 12% because one node is CPU saturated.",
            ),
        ],
        logs=[
            "sshd accepted publickey for deploy from 185.71.66.21 on web-node-3",
            "systemd started xmrig.service under root on web-node-3 after deploy account login",
            "falco: suspicious outbound connection from web-node-3 to pool.supportxmr.example:3333",
        ],
        services_status={
            "public-api": ServiceHealth.degraded,
            "web-node-3": ServiceHealth.degraded,
            "payments-worker": ServiceHealth.up,
            "identity-service": ServiceHealth.up,
        },
        expected_classification="security",
        expected_priority="P1",
        root_cause_aliases=[
            ["compromised", "deploy", "key", "miner"],
            ["stolen", "ssh", "key", "xmrig"],
            ["deploy credential", "crypto miner"],
        ],
        fix_aliases=[
            ["isolate", "web node 3", "revoke", "deploy key"],
            ["remove from rotation", "rotate", "deploy key", "rebuild"],
            ["drain", "revoke", "redeploy"],
        ],
        execution_aliases=[
            ["isolated", "web node 3", "revoked", "deploy key"],
            ["removed from rotation", "rotated", "deploy key", "rebuilt"],
            ["drained", "reimaged", "web node 3"],
        ],
        recommended_escalation="security-oncall",
        component_weights={
            "classification": 0.15,
            "priority": 0.2,
            "root_cause": 0.2,
            "fix_proposal": 0.15,
            "fix_execution": 0.2,
            "resolution": 0.1,
        },
        max_steps=8,
    ),
}

TASK_ORDER = list(TASKS.keys())


def get_task(task_id: str) -> IncidentTask:
    try:
        return TASKS[task_id]
    except KeyError as exc:
        raise KeyError(f"Unknown task_id: {task_id}") from exc


def list_tasks() -> list[IncidentTask]:
    return [TASKS[task_id] for task_id in TASK_ORDER]
