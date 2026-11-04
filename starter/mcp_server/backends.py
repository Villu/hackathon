"""Tool backends: deterministic mock fixtures and a real Azure implementation.

The mock is what the eval harness runs against (reproducible). The Azure backend uses the
`az login` credential (DefaultAzureCredential) and needs `pip install -e ".[azure]"`.
`execute_action` NEVER changes anything in Azure in this starter — it records a dry run.
"""

from __future__ import annotations

import hashlib
import logging
import random
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

logger = logging.getLogger("mcp_server.backends")

ALLOWED_ACTIONS = {"restart_revision", "rollback_deployment", "scale_out", "silence_alert", "acknowledge"}


class Backend(Protocol):
    def get_resource_state(self, resource_group: str, resource_name: str) -> dict[str, Any]: ...
    def get_deployment_history(self, resource_group: str, resource_name: str, limit: int) -> dict[str, Any]: ...
    def query_logs(self, resource_name: str, since_minutes: int, pattern: str | None, limit: int) -> dict[str, Any]: ...
    def get_alert_history(self, resource_name: str, hours: int) -> dict[str, Any]: ...
    def execute_action(self, action: str, resource_group: str, resource_name: str, dry_run: bool) -> dict[str, Any]: ...


# =============================================================================== mock
_PROFILES: dict[str, dict[str, Any]] = {
    # A bad deploy 4 minutes ago → 5xx storm.
    "orders-api": {
        "story": "deployment_regression",
        "cpu": 41.0,
        "memory": 58.0,
        "replicas": 3,
        "min": 2,
        "max": 6,
        "status": "Running",
        "revisions": [
            ("orders-api:2.14.0", 4, 100, "Healthy", "ci-bot"),
            ("orders-api:2.13.2", 3 * 24 * 60, 0, "Healthy", "ci-bot"),
            ("orders-api:2.13.1", 9 * 24 * 60, 0, "Healthy", "m.hansen"),
        ],
        "log_lines": [
            ("ERROR", "HTTP 500 GET /api/orders/{id} NullReferenceException at OrderMapper.MapV2 (OrderMapper.cs:88)"),
            ("ERROR", "HTTP 500 POST /api/orders ArgumentNullException: discountCode"),
            ("WARN", "Retrying downstream call to pricing-svc (attempt 2)"),
            ("INFO", "HTTP 200 GET /health"),
        ],
        "error_ratio": 0.6,
        "alerts": [("HighErrorRate", "critical", 2), ("HighLatencyP95", "warning", 3)],
    },
    # Upstream DB proxy refusing connections.
    "payments-worker": {
        "story": "dependency_failure",
        "cpu": 12.0,
        "memory": 35.0,
        "replicas": 2,
        "min": 2,
        "max": 4,
        "status": "Running",
        "revisions": [
            ("payments-worker:1.8.3", 6 * 24 * 60, 100, "Healthy", "ci-bot"),
            ("payments-worker:1.8.2", 20 * 24 * 60, 0, "Healthy", "ci-bot"),
        ],
        "log_lines": [
            ("ERROR", "connection refused: inventory-db-proxy:5432 (psycopg.OperationalError) after 3 retries"),
            ("ERROR", "job payments.settle failed: could not connect to inventory-db-proxy"),
            ("WARN", "circuit open for inventory-db-proxy, sleeping 5s"),
            ("INFO", "heartbeat ok"),
        ],
        "error_ratio": 0.5,
        "alerts": [("UpstreamConnectionRefused", "critical", 0.2)],
    },
    # Memory pressure → OOM kills.
    "checkout-frontend": {
        "story": "resource_exhaustion",
        "cpu": 63.0,
        "memory": 96.5,
        "replicas": 4,
        "min": 2,
        "max": 4,
        "status": "Running",
        "revisions": [
            ("checkout-frontend:5.2.0", 2 * 24 * 60, 100, "Healthy", "ci-bot"),
            ("checkout-frontend:5.1.9", 12 * 24 * 60, 0, "Healthy", "ci-bot"),
        ],
        "log_lines": [
            ("ERROR", "container killed: OOMKilled (exit 137), memory limit 512Mi"),
            ("WARN", "GC pressure: heap 498Mi / 512Mi"),
            ("WARN", "image cache size 310Mi exceeds soft limit"),
            ("INFO", "served /checkout in 210ms"),
        ],
        "error_ratio": 0.3,
        "alerts": [("ContainerOOMKilled", "critical", 1), ("HighMemoryUsage", "warning", 5)],
    },
    # Healthy, just busy.
    "search-indexer": {
        "story": "traffic_spike",
        "cpu": 78.0,
        "memory": 44.0,
        "replicas": 6,
        "min": 2,
        "max": 10,
        "status": "Running",
        "revisions": [("search-indexer:0.9.4", 15 * 24 * 60, 100, "Healthy", "ci-bot")],
        "log_lines": [
            ("INFO", "indexed batch of 5000 docs in 1.9s"),
            ("INFO", "queue depth 12000 (autoscaling to 7 replicas)"),
            ("WARN", "p95 latency 850ms above SLO 500ms"),
        ],
        "error_ratio": 0.0,
        "alerts": [("RequestRateHigh", "warning", 0.5)],
    },
}
_DEFAULT_PROFILE = {
    "story": "unknown",
    "cpu": 30.0,
    "memory": 40.0,
    "replicas": 2,
    "min": 1,
    "max": 3,
    "status": "Running",
    "revisions": [("app:1.0.0", 30 * 24 * 60, 100, "Healthy", "ci-bot")],
    "log_lines": [("INFO", "ok"), ("WARN", "slow request 900ms")],
    "error_ratio": 0.05,
    "alerts": [],
}


class MockBackend:
    def __init__(self, now: datetime | None = None) -> None:
        self._now = now

    def _now_(self) -> datetime:
        return self._now or datetime.now(UTC)

    def _profile(self, name: str) -> dict[str, Any]:
        return _PROFILES.get(name, _DEFAULT_PROFILE)

    def _rng(self, *parts: Any) -> random.Random:
        seed = int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest(), 16) % (2**32)
        return random.Random(seed)

    def get_resource_state(self, resource_group: str, resource_name: str) -> dict[str, Any]:
        p = self._profile(resource_name)
        now = self._now_()
        return {
            "resource_group": resource_group,
            "resource_name": resource_name,
            "type": "Microsoft.App/containerApps",
            "provisioning_state": "Succeeded",
            "running_status": p["status"],
            "replicas": {"current": p["replicas"], "min": p["min"], "max": p["max"]},
            "cpu_percent": p["cpu"],
            "memory_percent": p["memory"],
            "latest_revision": p["revisions"][0][0].split(":")[-1],
            "last_restart": (now - timedelta(minutes=p["revisions"][0][1])).isoformat(timespec="seconds"),
            "source": "mock",
        }

    def get_deployment_history(self, resource_group: str, resource_name: str, limit: int) -> dict[str, Any]:
        p = self._profile(resource_name)
        now = self._now_()
        revisions = []
        for i, (image, minutes_ago, traffic, health, who) in enumerate(p["revisions"][:limit]):
            revisions.append(
                {
                    "revision": f"{resource_name}--rev{len(p['revisions']) - i:04d}",
                    "image": image,
                    "created_at": (now - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds"),
                    "minutes_ago": minutes_ago,
                    "traffic_weight": traffic,
                    "health_state": health,
                    "deployed_by": who,
                    "active": traffic > 0,
                }
            )
        return {"resource_name": resource_name, "revisions": revisions, "source": "mock"}

    def query_logs(self, resource_name: str, since_minutes: int, pattern: str | None, limit: int) -> dict[str, Any]:
        p = self._profile(resource_name)
        rng = self._rng(resource_name, since_minutes, pattern, limit)
        now = self._now_()
        lines = []
        errors = 0
        for _ in range(min(limit, 50)):
            level, msg = rng.choice(p["log_lines"])
            if p["error_ratio"] and rng.random() < p["error_ratio"]:
                level, msg = next(((lv, m) for lv, m in p["log_lines"] if lv == "ERROR"), (level, msg))
            if pattern and pattern.lower() not in msg.lower():
                continue
            ts = now - timedelta(seconds=rng.uniform(0, since_minutes * 60))
            if level == "ERROR":
                errors += 1
            lines.append({"ts": ts.isoformat(timespec="seconds"), "level": level, "message": msg})
        lines.sort(key=lambda x: x["ts"], reverse=True)
        return {
            "resource_name": resource_name,
            "since_minutes": since_minutes,
            "pattern": pattern,
            "count": len(lines),
            "error_count": errors,
            "lines": lines,
            "source": "mock",
        }

    def get_alert_history(self, resource_name: str, hours: int) -> dict[str, Any]:
        p = self._profile(resource_name)
        now = self._now_()
        alerts = [
            {"name": name, "severity": sev, "fired_at": (now - timedelta(hours=h)).isoformat(timespec="seconds")}
            for name, sev, h in p["alerts"]
            if h <= hours
        ]
        return {"resource_name": resource_name, "hours": hours, "alerts": alerts, "source": "mock"}

    def execute_action(self, action: str, resource_group: str, resource_name: str, dry_run: bool) -> dict[str, Any]:
        if action not in ALLOWED_ACTIONS:
            return {"ok": False, "error": f"action {action!r} is not allowed", "allowed": sorted(ALLOWED_ACTIONS)}
        logger.warning("execute_action %s on %s/%s dry_run=%s", action, resource_group, resource_name, dry_run)
        return {
            "ok": True,
            "action": action,
            "resource_group": resource_group,
            "resource_name": resource_name,
            "dry_run": dry_run,
            "executed": False,  # the starter never executes; teams may simulate in dev
            "note": "simulated — no change made",
            "source": "mock",
        }


# =============================================================================== azure
class AzureBackend:
    """Reads Container Apps state/revisions and Log Analytics logs with the `az login` credential.

    Written against the current azure-sdk APIs but NOT exercised in the starter's CI — expect
    to adjust field names on first contact. Every method returns a dict, never raises.
    """

    def __init__(self, subscription_id: str, workspace_id: str | None) -> None:
        from azure.identity import DefaultAzureCredential  # lazy: optional extra

        self.subscription_id = subscription_id
        self.workspace_id = workspace_id
        self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        self._apps = None
        self._logs = None

    def _apps_client(self):
        if self._apps is None:
            from azure.mgmt.appcontainers import ContainerAppsAPIClient

            self._apps = ContainerAppsAPIClient(self.credential, self.subscription_id)
        return self._apps

    def _logs_client(self):
        if self._logs is None:
            from azure.monitor.query import LogsQueryClient

            self._logs = LogsQueryClient(self.credential)
        return self._logs

    def get_resource_state(self, resource_group: str, resource_name: str) -> dict[str, Any]:
        try:
            app = self._apps_client().container_apps.get(resource_group, resource_name)
            scale = getattr(getattr(app, "template", None), "scale", None)
            return {
                "resource_group": resource_group,
                "resource_name": resource_name,
                "type": "Microsoft.App/containerApps",
                "provisioning_state": str(app.provisioning_state),
                "running_status": str(getattr(app, "running_status", "unknown")),
                "latest_revision": app.latest_revision_name,
                "latest_ready_revision": getattr(app, "latest_ready_revision_name", None),
                "replicas": {"min": getattr(scale, "min_replicas", None), "max": getattr(scale, "max_replicas", None)},
                "fqdn": getattr(getattr(app, "configuration", None), "ingress", None)
                and app.configuration.ingress.fqdn,
                "source": "azure",
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"[:300], "source": "azure"}

    def get_deployment_history(self, resource_group: str, resource_name: str, limit: int) -> dict[str, Any]:
        try:
            revs = list(self._apps_client().container_apps_revisions.list_revisions(resource_group, resource_name))
            revs.sort(key=lambda r: r.created_time or datetime.min.replace(tzinfo=UTC), reverse=True)
            now = datetime.now(UTC)
            out = []
            for r in revs[:limit]:
                containers = getattr(getattr(r, "template", None), "containers", None) or []
                created = r.created_time
                out.append(
                    {
                        "revision": r.name,
                        "image": containers[0].image if containers else None,
                        "created_at": created.isoformat(timespec="seconds") if created else None,
                        "minutes_ago": int((now - created).total_seconds() // 60) if created else None,
                        "traffic_weight": getattr(r, "traffic_weight", None),
                        "health_state": str(getattr(r, "health_state", "unknown")),
                        "active": bool(getattr(r, "active", False)),
                    }
                )
            return {"resource_name": resource_name, "revisions": out, "source": "azure"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"[:300], "source": "azure"}

    def query_logs(self, resource_name: str, since_minutes: int, pattern: str | None, limit: int) -> dict[str, Any]:
        if not self.workspace_id:
            return {"error": "LOG_ANALYTICS_WORKSPACE_ID not set", "source": "azure"}
        safe_name = resource_name.replace("'", "")
        where_pattern = f"| where Log_s has '{pattern.replace(chr(39), '')}'" if pattern else ""
        kql = f"""
ContainerAppConsoleLogs_CL
| where ContainerAppName_s == '{safe_name}'
| where TimeGenerated > ago({int(since_minutes)}m)
{where_pattern}
| project TimeGenerated, Log_s, RevisionName_s
| order by TimeGenerated desc
| take {int(limit)}
"""
        try:
            from azure.monitor.query import LogsQueryStatus

            resp = self._logs_client().query_workspace(
                self.workspace_id, kql, timespan=timedelta(minutes=since_minutes)
            )
            if resp.status != LogsQueryStatus.SUCCESS:
                return {"error": f"query status {resp.status}", "source": "azure"}
            lines = []
            errors = 0
            for table in resp.tables:
                for row in table.rows:
                    ts, msg, rev = row[0], str(row[1]), row[2]
                    level = (
                        "ERROR"
                        if any(k in msg.lower() for k in ("error", "exception", " 500 ", "oomkilled", "refused"))
                        else "INFO"
                    )
                    errors += level == "ERROR"
                    lines.append({"ts": str(ts), "level": level, "message": msg[:500], "revision": rev})
            return {
                "resource_name": resource_name,
                "since_minutes": since_minutes,
                "pattern": pattern,
                "count": len(lines),
                "error_count": errors,
                "lines": lines,
                "source": "azure",
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"[:300], "source": "azure"}

    def get_alert_history(self, resource_name: str, hours: int) -> dict[str, Any]:
        try:
            from azure.mgmt.alertsmanagement import AlertsManagementClient

            client = AlertsManagementClient(self.credential, self.subscription_id)
            time_range = "1h" if hours <= 1 else "1d" if hours <= 24 else "7d"
            alerts = []
            for a in client.alerts.get_all(time_range=time_range):
                target = str(getattr(a.properties.essentials, "target_resource_name", "") or "")
                if target.lower() != resource_name.lower():
                    continue
                ess = a.properties.essentials
                alerts.append({"name": a.name, "severity": str(ess.severity), "fired_at": str(ess.start_date_time)})
            return {"resource_name": resource_name, "hours": hours, "alerts": alerts, "source": "azure"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"[:300], "source": "azure"}

    def execute_action(self, action: str, resource_group: str, resource_name: str, dry_run: bool) -> dict[str, Any]:
        # Deliberately identical to the mock: the starter never mutates Azure.
        return MockBackend().execute_action(action, resource_group, resource_name, dry_run) | {
            "source": "azure-dry-run"
        }
