import pytest

from gateway.models import Environment, Severity
from gateway.stream.normalise import NormalisationError, normalise
from simulator.scenarios import deployment_regression, to_azure, to_prometheus


def test_prometheus_webhook_is_normalised():
    raw = to_prometheus(deployment_regression("staging"))
    alerts = normalise(raw)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.name == "HighErrorRate"
    assert a.severity is Severity.critical
    assert a.resource.name == "orders-api"
    assert a.resource.environment is Environment.staging
    assert a.value == 23.5
    assert a.alert_id == raw["alerts"][0]["fingerprint"]


def test_azure_common_alert_schema_is_normalised():
    raw = to_azure(deployment_regression("prod"))
    a = normalise(raw)[0]
    assert a.source == "azure_monitor"
    assert a.resource.resource_group == "VilluResourceGroup"
    assert a.resource.name == "orders-api"
    assert a.resource.type == "Microsoft.App/containerApps"
    assert a.severity is Severity.critical
    assert a.resource.environment is Environment.prod


def test_list_and_normalised_shape():
    a1 = deployment_regression()
    a2 = deployment_regression()
    alerts = normalise([a1, a2])
    assert [a.alert_id for a in alerts] == [a1["alert_id"], a2["alert_id"]]


def test_unknown_environment_defaults_to_prod():
    raw = deployment_regression()
    raw["resource"]["environment"] = "prod"
    raw["labels"] = {}
    assert normalise(raw)[0].resource.environment is Environment.prod


def test_garbage_is_rejected():
    with pytest.raises(NormalisationError):
        normalise({"hello": "world"})
    with pytest.raises(NormalisationError):
        normalise("nope")
