import json

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app.main import create_app

INCIDENT = {"caller_phone": "+2348012345678", "latitude": 6.5095, "longitude": 3.3711, "severity": 4}


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    for key, value in {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_REGION": "us-east-1"}.items():
        monkeypatch.setenv(key, value)
    with mock_aws():
        dynamodb = boto3.client("dynamodb", region_name="us-east-1")
        for table, key in (("rescueops-incidents", "incident_id"), ("rescueops-ambulances", "ambulance_id")):
            dynamodb.create_table(
                TableName=table,
                KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
        sqs = boto3.client("sqs", region_name="us-east-1")
        yield sqs.create_queue(QueueName="rescueops-dispatch-requests")["QueueUrl"]


@pytest.fixture
def client(aws):
    with TestClient(create_app()) as test_client:
        yield test_client


def test_health_and_readiness(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200


def test_report_incident_persists_and_enqueues(client, aws):
    response = client.post("/v1/incidents", json=INCIDENT)
    assert response.status_code == 202
    incident = response.json()
    assert incident["status"] == "PENDING"

    fetched = client.get(f"/v1/incidents/{incident['incident_id']}").json()
    assert fetched["severity"] == 4
    assert fetched["latitude"] == pytest.approx(6.5095)

    messages = boto3.client("sqs", region_name="us-east-1").receive_message(QueueUrl=aws)["Messages"]
    body = json.loads(messages[0]["Body"])
    assert body["incident_id"] == incident["incident_id"]
    assert "caller_phone" not in body


@pytest.mark.parametrize(
    "override",
    [{"severity": 9}, {"latitude": 120}, {"caller_phone": "not-a-phone"}],
)
def test_rejects_invalid_incident(client, override):
    assert client.post("/v1/incidents", json={**INCIDENT, **override}).status_code == 422


def test_unknown_incident_returns_404(client):
    assert client.get("/v1/incidents/does-not-exist").status_code == 404


def test_register_and_list_ambulances(client):
    ambulance = {"ambulance_id": "LAG-AMB-001", "latitude": 6.6018, "longitude": 3.3515}
    created = client.post("/v1/ambulances", json=ambulance)
    assert created.status_code == 201
    assert created.json()["status"] == "AVAILABLE"
    assert [a["ambulance_id"] for a in client.get("/v1/ambulances").json()] == ["LAG-AMB-001"]


def test_metrics_use_route_templates(client):
    client.get("/v1/incidents/some-id")
    metrics = client.get("/metrics").text
    assert 'route="/v1/incidents/{incident_id}"' in metrics
    assert "some-id" not in metrics


def test_readiness_fails_when_dependencies_missing(client):
    boto3.client("dynamodb", region_name="us-east-1").delete_table(TableName="rescueops-incidents")
    assert client.get("/readyz").status_code == 503
