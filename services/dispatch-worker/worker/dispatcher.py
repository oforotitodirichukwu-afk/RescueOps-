import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

from .config import Settings
from .matcher import eta_minutes, rank_by_distance

log = logging.getLogger("dispatch-worker")


class Outcome(StrEnum):
    DISPATCHED = "dispatched"
    NO_AMBULANCE = "no_ambulance"
    DUPLICATE = "duplicate"


class Dispatcher:
    def __init__(self, settings: Settings, session: boto3.session.Session):
        dynamodb = session.resource("dynamodb")
        self._incidents = dynamodb.Table(settings.incidents_table)
        self._ambulances = dynamodb.Table(settings.ambulances_table)
        self._dynamodb = dynamodb.meta.client
        self._s3 = session.client("s3")
        self._bucket = settings.reports_bucket
        self._speed_kmh = settings.ambulance_speed_kmh

    def process(self, request: dict) -> Outcome:
        incident_id = request["incident_id"]
        # SQS delivers at least once, so a redelivered request must not dispatch a second ambulance.
        if not self._is_pending(incident_id):
            return Outcome.DUPLICATE

        for distance_km, ambulance in rank_by_distance(self._available(), request["latitude"], request["longitude"]):
            record = self._claim(incident_id, ambulance["ambulance_id"], distance_km)
            if record:
                self._write_report(record)
                log.info("ambulance dispatched", extra={"fields": record})
                return Outcome.DISPATCHED
            if not self._is_pending(incident_id):
                return Outcome.DUPLICATE
        return Outcome.NO_AMBULANCE

    def _is_pending(self, incident_id: str) -> bool:
        item = self._incidents.get_item(Key={"incident_id": incident_id}, ConsistentRead=True).get("Item")
        return bool(item) and item["status"] == "PENDING"

    def _available(self) -> list[dict]:
        items, kwargs = [], {"FilterExpression": Attr("status").eq("AVAILABLE")}
        while True:
            page = self._ambulances.scan(**kwargs)
            items.extend(page["Items"])
            if "LastEvaluatedKey" not in page:
                return items
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def _claim(self, incident_id: str, ambulance_id: str, distance_km: float) -> dict | None:
        """Atomically assign the ambulance and the incident; returns None if either was taken first."""
        now = datetime.now(UTC).isoformat()
        distance = round(distance_km, 2)
        eta = eta_minutes(distance_km, self._speed_kmh)
        try:
            self._dynamodb.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": self._ambulances.name,
                            "Key": {"ambulance_id": ambulance_id},
                            "UpdateExpression": "SET #s = :dispatched, incident_id = :incident, updated_at = :now",
                            "ConditionExpression": "#s = :available",
                            "ExpressionAttributeNames": {"#s": "status"},
                            "ExpressionAttributeValues": {
                                ":dispatched": "DISPATCHED",
                                ":available": "AVAILABLE",
                                ":incident": incident_id,
                                ":now": now,
                            },
                        }
                    },
                    {
                        "Update": {
                            "TableName": self._incidents.name,
                            "Key": {"incident_id": incident_id},
                            "UpdateExpression": "SET #s = :dispatched, ambulance_id = :ambulance, "
                            "distance_km = :distance, eta_minutes = :eta, dispatched_at = :now",
                            "ConditionExpression": "#s = :pending",
                            "ExpressionAttributeNames": {"#s": "status"},
                            "ExpressionAttributeValues": {
                                ":dispatched": "DISPATCHED",
                                ":pending": "PENDING",
                                ":ambulance": ambulance_id,
                                ":distance": Decimal(str(distance)),
                                ":eta": Decimal(str(eta)),
                                ":now": now,
                            },
                        }
                    },
                ]
            )
        except ClientError as err:
            if err.response["Error"]["Code"] == "TransactionCanceledException":
                return None
            raise
        return {
            "incident_id": incident_id,
            "ambulance_id": ambulance_id,
            "distance_km": distance,
            "eta_minutes": eta,
            "dispatched_at": now,
        }

    def _write_report(self, record: dict) -> None:
        key = f"dispatches/{record['dispatched_at'][:10]}/{record['incident_id']}.json"
        self._s3.put_object(
            Bucket=self._bucket, Key=key, Body=json.dumps(record).encode(), ContentType="application/json"
        )
