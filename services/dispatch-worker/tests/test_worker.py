import json
from datetime import UTC, datetime
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from worker.config import load_settings
from worker.dispatcher import Dispatcher, Outcome
from worker.main import handle
from worker.matcher import eta_minutes, haversine_km, rank_by_distance

REGION = "us-east-1"
YABA = (6.5095, 3.3711)
IKEJA = (6.6018, 3.3515)
LEKKI = (6.4478, 3.4723)


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    for key, value in {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_REGION": REGION}.items():
        monkeypatch.setenv(key, value)
    with mock_aws():
        dynamodb = boto3.client("dynamodb", region_name=REGION)
        for table, key in (("rescueops-incidents", "incident_id"), ("rescueops-ambulances", "ambulance_id")):
            dynamodb.create_table(
                TableName=table,
                KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
        boto3.client("s3", region_name=REGION).create_bucket(Bucket="rescueops-dispatch-reports")
        boto3.client("sqs", region_name=REGION).create_queue(QueueName="rescueops-dispatch-requests")
        yield boto3.resource("dynamodb", region_name=REGION)


@pytest.fixture
def dispatcher(aws):
    return Dispatcher(load_settings(), boto3.session.Session(region_name=REGION))


def add_incident(aws, incident_id: str, location=YABA) -> dict:
    lat, lon = location
    created_at = datetime.now(UTC).isoformat()
    aws.Table("rescueops-incidents").put_item(
        Item={
            "incident_id": incident_id,
            "status": "PENDING",
            "latitude": Decimal(str(lat)),
            "longitude": Decimal(str(lon)),
            "severity": 4,
            "created_at": created_at,
        }
    )
    return {"incident_id": incident_id, "latitude": lat, "longitude": lon, "severity": 4, "created_at": created_at}


def add_ambulance(aws, ambulance_id: str, location, status="AVAILABLE") -> None:
    lat, lon = location
    item = {"ambulance_id": ambulance_id, "status": status}
    item.update(latitude=Decimal(str(lat)), longitude=Decimal(str(lon)))
    aws.Table("rescueops-ambulances").put_item(Item=item)


def status_of(aws, table: str, key: str, value: str) -> dict:
    return aws.Table(table).get_item(Key={key: value})["Item"]


def test_haversine_one_degree_latitude():
    assert haversine_km(0, 0, 0, 0) == 0
    assert haversine_km(0, 0, 1, 0) == pytest.approx(111.19, abs=0.01)


def test_rank_by_distance_orders_nearest_first():
    ambulances = [{"id": "lekki", "latitude": LEKKI[0], "longitude": LEKKI[1]},
                  {"id": "ikeja", "latitude": IKEJA[0], "longitude": IKEJA[1]}]
    assert [a["id"] for _, a in rank_by_distance(ambulances, *YABA)] == ["ikeja", "lekki"]


def test_eta_minutes():
    assert eta_minutes(20, 40) == 30.0


def test_dispatches_nearest_available_ambulance(aws, dispatcher):
    request = add_incident(aws, "inc-1")
    add_ambulance(aws, "AMB-IKEJA", IKEJA)
    add_ambulance(aws, "AMB-LEKKI", LEKKI)

    assert dispatcher.process(request) is Outcome.DISPATCHED

    incident = status_of(aws, "rescueops-incidents", "incident_id", "inc-1")
    assert incident["status"] == "DISPATCHED"
    assert incident["ambulance_id"] == "AMB-IKEJA"
    assert status_of(aws, "rescueops-ambulances", "ambulance_id", "AMB-IKEJA")["status"] == "DISPATCHED"
    assert status_of(aws, "rescueops-ambulances", "ambulance_id", "AMB-LEKKI")["status"] == "AVAILABLE"

    reports = boto3.client("s3", region_name=REGION).list_objects_v2(Bucket="rescueops-dispatch-reports")
    assert reports["Contents"][0]["Key"].endswith("/inc-1.json")


def test_no_ambulance_leaves_incident_pending(aws, dispatcher):
    request = add_incident(aws, "inc-1")
    add_ambulance(aws, "AMB-BUSY", IKEJA, status="DISPATCHED")

    assert dispatcher.process(request) is Outcome.NO_AMBULANCE
    assert status_of(aws, "rescueops-incidents", "incident_id", "inc-1")["status"] == "PENDING"


def test_redelivered_request_does_not_dispatch_twice(aws, dispatcher):
    request = add_incident(aws, "inc-1")
    add_ambulance(aws, "AMB-IKEJA", IKEJA)
    add_ambulance(aws, "AMB-LEKKI", LEKKI)

    assert dispatcher.process(request) is Outcome.DISPATCHED
    assert dispatcher.process(request) is Outcome.DUPLICATE
    assert status_of(aws, "rescueops-ambulances", "ambulance_id", "AMB-LEKKI")["status"] == "AVAILABLE"


def test_skips_ambulance_claimed_by_another_worker(aws, dispatcher, monkeypatch):
    request = add_incident(aws, "inc-1")
    add_ambulance(aws, "AMB-IKEJA", IKEJA, status="DISPATCHED")
    add_ambulance(aws, "AMB-LEKKI", LEKKI)
    stale_view = [
        {"ambulance_id": "AMB-IKEJA", "latitude": IKEJA[0], "longitude": IKEJA[1]},
        {"ambulance_id": "AMB-LEKKI", "latitude": LEKKI[0], "longitude": LEKKI[1]},
    ]
    monkeypatch.setattr(dispatcher, "_available", lambda: stale_view)

    assert dispatcher.process(request) is Outcome.DISPATCHED
    assert status_of(aws, "rescueops-incidents", "incident_id", "inc-1")["ambulance_id"] == "AMB-LEKKI"


def _receive(sqs, queue_url, body: str) -> dict:
    sqs.send_message(QueueUrl=queue_url, MessageBody=body)
    return sqs.receive_message(QueueUrl=queue_url)["Messages"][0]


def _queue_depth(sqs, queue_url) -> int:
    attrs = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["All"])["Attributes"]
    return int(attrs["ApproximateNumberOfMessages"]) + int(attrs["ApproximateNumberOfMessagesNotVisible"])


def test_handle_deletes_message_after_dispatch(aws, dispatcher):
    sqs = boto3.client("sqs", region_name=REGION)
    queue_url = sqs.get_queue_url(QueueName="rescueops-dispatch-requests")["QueueUrl"]
    request = add_incident(aws, "inc-1")
    add_ambulance(aws, "AMB-IKEJA", IKEJA)

    message = _receive(sqs, queue_url, json.dumps(request))
    assert handle(dispatcher, sqs, queue_url, message, retry_delay=15) is Outcome.DISPATCHED
    assert _queue_depth(sqs, queue_url) == 0


def test_handle_keeps_message_for_retry_when_no_ambulance(aws, dispatcher):
    sqs = boto3.client("sqs", region_name=REGION)
    queue_url = sqs.get_queue_url(QueueName="rescueops-dispatch-requests")["QueueUrl"]
    message = _receive(sqs, queue_url, json.dumps(add_incident(aws, "inc-1")))

    assert handle(dispatcher, sqs, queue_url, message, retry_delay=15) is Outcome.NO_AMBULANCE
    assert _queue_depth(sqs, queue_url) == 1


def test_handle_survives_malformed_message(aws, dispatcher):
    sqs = boto3.client("sqs", region_name=REGION)
    queue_url = sqs.get_queue_url(QueueName="rescueops-dispatch-requests")["QueueUrl"]
    message = _receive(sqs, queue_url, "not json")

    assert handle(dispatcher, sqs, queue_url, message, retry_delay=15) is None
    assert _queue_depth(sqs, queue_url) == 1
