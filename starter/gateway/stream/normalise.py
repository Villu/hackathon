"""Turn whatever the alerting system sends into `Alert` objects (spec 3.1).

Accepted shapes:
  * already-normalised Alert dicts (single or list)
  * Prometheus Alertmanager webhook: {"alerts": [{"labels": {...}, "annotations": {...}, ...}]}
  * Azure Monitor common alert schema: {"schemaId": "azureMonitorCommonAlertSchema", "data": {...}}
Unknown fields are kept in labels/annotations, never dropped silently.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from gateway.models import Alert, AlertStatus, Environment, ResourceRef, Severity

_AZ_RESOURCE_RE = re.compile(
    r"/subscriptions/(?P<sub>[^/]+)/resourceGroups/(?P<rg>[^/]+)/providers/"
    r"(?P<type>[^/]+/[^/]+)/(?P<name>[^/]+)",
    re.IGNORECASE,
)

_SEVERITY_WORDS = {
    "critical": Severity.critical,
    "page": Severity.critical,
    "error": Severity.critical,
    "warning": Severity.warning,
    "warn": Severity.warning,
    "info": Severity.info,
    "informational": Severity.info,
    "none": Severity.info,
}
_AZ_SEV = {"sev0": Severity.critical, "sev1": Severity.critical, "sev2": Severity.warning}


class NormalisationError(ValueError):
    pass


def normalise(payload: Any) -> list[Alert]:
    if isinstance(payload, list):
        out: list[Alert] = []
        for item in payload:
            out.extend(normalise(item))
        return out
    if not isinstance(payload, dict):
        raise NormalisationError(f"unsupported payload type {type(payload).__name__}")

    if payload.get("schemaId") == "azureMonitorCommonAlertSchema":
        return [_from_azure(payload)]
    if "alerts" in payload and isinstance(payload["alerts"], list):
        return [_from_prometheus(a, payload) for a in payload["alerts"]]
    if "alert_id" in payload and "severity" in payload:
        return [Alert.model_validate(payload)]
    if "labels" in payload and "annotations" in payload:  # single Alertmanager alert
        return [_from_prometheus(payload, {})]
    raise NormalisationError("unrecognised alert shape")


# --------------------------------------------------------------------------- helpers
def _stable_id(*parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return "a-" + hashlib.sha1(raw.encode()).hexdigest()[:16]


def _severity(word: str | None, default: Severity = Severity.warning) -> Severity:
    if not word:
        return default
    return _SEVERITY_WORDS.get(word.lower(), default)


def _environment(labels: dict[str, str]) -> Environment:
    for key in ("environment", "env", "stage", "tier"):
        val = labels.get(key, "").lower()
        if val.startswith("prod"):
            return Environment.prod
        if val.startswith("stag") or val in {"test", "qa", "preprod"}:
            return Environment.staging
        if val.startswith("dev"):
            return Environment.dev
    return Environment.prod  # unknown → treat as prod (safest allowlist)


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)


def _from_prometheus(alert: dict[str, Any], envelope: dict[str, Any]) -> Alert:
    labels = {k: str(v) for k, v in (alert.get("labels") or {}).items()}
    annotations = {k: str(v) for k, v in (alert.get("annotations") or {}).items()}
    name = labels.get("alertname", "UnknownAlert")
    resource_name = (
        labels.get("resource_name")
        or labels.get("app")
        or labels.get("service")
        or labels.get("deployment")
        or labels.get("pod")
        or labels.get("instance")
        or "unknown"
    )
    value = None
    for key in ("value", "current_value"):
        if key in annotations:
            try:
                value = float(annotations[key])
            except ValueError:
                pass
    return Alert(
        alert_id=alert.get("fingerprint") or _stable_id(labels, alert.get("startsAt")),
        source=labels.get("source", "prometheus"),
        name=name,
        severity=_severity(labels.get("severity")),
        status=AlertStatus(alert.get("status", "firing"))
        if alert.get("status") in ("firing", "resolved")
        else AlertStatus.firing,
        starts_at=_parse_time(alert.get("startsAt")),
        resource=ResourceRef(
            resource_group=labels.get("resource_group", "VilluResourceGroup"),
            type=labels.get("resource_type"),
            name=resource_name,
            environment=_environment(labels),
        ),
        labels=labels,
        annotations=annotations,
        value=value,
        eval=alert.get("eval") or envelope.get("eval"),
    )


def _from_azure(payload: dict[str, Any]) -> Alert:
    data = payload.get("data") or {}
    ess = data.get("essentials") or {}
    ctx = data.get("alertContext") or {}
    targets = ess.get("alertTargetIDs") or []
    resource = ResourceRef(name="unknown")
    labels: dict[str, str] = {}
    if targets:
        m = _AZ_RESOURCE_RE.search(targets[0])
        if m:
            resource = ResourceRef(
                subscription_id=m.group("sub"),
                resource_group=m.group("rg"),
                type=m.group("type"),
                name=m.group("name"),
            )
    custom = ess.get("customProperties") or {}
    labels.update({k: str(v) for k, v in custom.items()})
    resource.environment = _environment(labels)
    condition = (ctx.get("condition") or {}).get("allOf") or [{}]
    metric_value = condition[0].get("metricValue") if condition else None
    annotations = {
        "summary": ess.get("description") or ess.get("alertRule", ""),
        "description": json.dumps(ctx, default=str)[:2000] if ctx else "",
    }
    sev = _AZ_SEV.get(str(ess.get("severity", "")).lower(), Severity.info)
    return Alert(
        alert_id=ess.get("alertId") or _stable_id(ess),
        source="azure_monitor",
        name=ess.get("alertRule", "AzureAlert"),
        severity=sev,
        status=AlertStatus.resolved
        if str(ess.get("monitorCondition", "")).lower() == "resolved"
        else AlertStatus.firing,
        starts_at=_parse_time(ess.get("firedDateTime")),
        resource=resource,
        labels=labels,
        annotations=annotations,
        value=float(metric_value) if isinstance(metric_value, int | float) else None,
        eval=payload.get("eval"),
    )
