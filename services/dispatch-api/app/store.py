import json
from decimal import Decimal

import boto3

from .config import Settings

DISPATCH_FIELDS = ("incident_id", "latitude", "longitude", "severity", "created_at")


def _to_dynamo(item: dict) -> dict:
    return {
        key: Decimal(str(value)) if isinstance(value, float) else value
        for key, value in item.items()
        if value is not None
    }


def _from_dynamo(item: dict) -> dict:
    def convert(value):
        if isinstance(value, Decimal):
            return int(value) if value == value.to_integral_value() else float(value)
        return value

    return {key: convert(value) for key, value in item.items()}


class Store:
    def __init__(self, settings: Settings):
        session = boto3.session.Session(region_name=settings.region)
        dynamodb = session.resource("dynamodb")
        self._incidents = dynamodb.Table(settings.incidents_table)
        self._ambulances = dynamodb.Table(settings.ambulances_table)
        self._sqs = session.client("sqs")
        self._queue_name = settings.dispatch_queue
        self._queue_url: str | None = None

    def _queue(self) -> str:
        if self._queue_url is None:
            self._queue_url = self._sqs.get_queue_url(QueueName=self._queue_name)["QueueUrl"]
        return self._queue_url

    def ping(self) -> None:
        self._incidents.load()
        self._ambulances.load()
        self._sqs.get_queue_attributes(QueueUrl=self._queue(), AttributeNames=["QueueArn"])

    def create_incident(self, incident: dict) -> None:
        self._incidents.put_item(Item=_to_dynamo(incident))
        request = {key: incident[key] for key in DISPATCH_FIELDS}
        self._sqs.send_message(QueueUrl=self._queue(), MessageBody=json.dumps(request))

    def get_incident(self, incident_id: str) -> dict | None:
        item = self._incidents.get_item(Key={"incident_id": incident_id}).get("Item")
        return _from_dynamo(item) if item else None

    def put_ambulance(self, ambulance: dict) -> None:
        self._ambulances.put_item(Item=_to_dynamo(ambulance))

    def list_ambulances(self) -> list[dict]:
        items, kwargs = [], {}
        while True:
            page = self._ambulances.scan(**kwargs)
            items.extend(_from_dynamo(item) for item in page["Items"])
            if "LastEvaluatedKey" not in page:
                return items
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
