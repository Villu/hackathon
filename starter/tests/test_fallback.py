import time

from gateway.models import AlertStatus, DecisionSource, Environment, RecommendedAction, RootCauseCategory, Severity
from gateway.reliability.fallback import deterministic_triage
from tests.conftest import make_alert


def test_info_is_no_action():
    d = deterministic_triage(make_alert(name="DiskUsageInfo", severity=Severity.info))
    assert d.recommended_action is RecommendedAction.no_action
    assert d.decision_source is DecisionSource.deterministic_fallback


def test_resolved_is_no_action():
    d = deterministic_triage(make_alert(status=AlertStatus.resolved))
    assert d.recommended_action is RecommendedAction.no_action


def test_cpu_alert_maps_to_resource_exhaustion_and_escalates():
    d = deterministic_triage(make_alert(name="HighCPUUsage"))
    assert d.root_cause_category is RootCauseCategory.resource_exhaustion
    assert d.recommended_action is RecommendedAction.escalate_to_oncall


def test_prod_never_gets_remediation_from_rules():
    for env in Environment:
        d = deterministic_triage(make_alert(name="RolloutFailed", env=env))
        if env is Environment.prod:
            assert d.recommended_action in {
                RecommendedAction.no_action,
                RecommendedAction.acknowledge,
                RecommendedAction.escalate_to_oncall,
            }


def test_unclassified_warning_is_acknowledged():
    d = deterministic_triage(make_alert(name="SomethingOdd", severity=Severity.warning))
    assert d.recommended_action is RecommendedAction.acknowledge


def test_fallback_is_fast():
    alert = make_alert(name="HighErrorRate")
    t0 = time.perf_counter()
    for _ in range(200):
        deterministic_triage(alert)
    per_call_ms = (time.perf_counter() - t0) * 1000 / 200
    assert per_call_ms < 20, f"{per_call_ms:.2f} ms per call"
