import json
import logging
import signal
import threading
from datetime import UTC, datetime

import boto3
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from .config import load_settings
from .dispatcher import Dispatcher, Outcome
from .logs import configure_logging

log = logging.getLogger("dispatch-worker")

OUTCOMES = Counter("rescueops_dispatch_outcomes_total", "Dispatch attempts by outcome", ["outcome"])
PROCESSING = Histogram("rescueops_dispatch_processing_seconds", "Time spent processing one dispatch request")
TIME_TO_DISPATCH = Histogram(
    "rescueops_time_to_dispatch_seconds",
    "Time from incident report to ambulance assignment",
    buckets=(1, 2, 5, 10, 30, 60, 120, 300, 600),
)
LAST_POLL = Gauge("rescueops_worker_last_poll_timestamp_seconds", "Unix time of the last successful queue poll")


def handle(dispatcher: Dispatcher, sqs, queue_url: str, message: dict, retry_delay: int) -> Outcome | None:
    receipt = message["ReceiptHandle"]
    with PROCESSING.time():
        try:
            request = json.loads(message["Body"])
            outcome = dispatcher.process(request)
        except Exception:
            # Left on the queue: it retries after the visibility timeout and lands in the DLQ if it keeps failing.
            OUTCOMES.labels("error").inc()
            log.exception("dispatch failed", extra={"fields": {"message_id": message.get("MessageId")}})
            return None

    OUTCOMES.labels(outcome.value).inc()
    if outcome is Outcome.NO_AMBULANCE:
        sqs.change_message_visibility(QueueUrl=queue_url, ReceiptHandle=receipt, VisibilityTimeout=retry_delay)
        log.warning("no ambulance available", extra={"fields": {"incident_id": request["incident_id"]}})
        return outcome

    if outcome is Outcome.DISPATCHED:
        reported = datetime.fromisoformat(request["created_at"])
        TIME_TO_DISPATCH.observe((datetime.now(UTC) - reported).total_seconds())
    sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
    return outcome


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    start_http_server(settings.metrics_port)

    session = boto3.session.Session(region_name=settings.region)
    dispatcher = Dispatcher(settings, session)
    sqs = session.client("sqs")
    queue_url = sqs.get_queue_url(QueueName=settings.dispatch_queue)["QueueUrl"]

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    log.info("worker started", extra={"fields": {"queue": settings.dispatch_queue}})
    while not stop.is_set():
        try:
            response = sqs.receive_message(
                QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=settings.poll_wait_seconds
            )
        except Exception:
            log.exception("queue poll failed")
            stop.wait(5)
            continue
        LAST_POLL.set_to_current_time()
        for message in response.get("Messages", []):
            handle(dispatcher, sqs, queue_url, message, settings.retry_delay_seconds)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
