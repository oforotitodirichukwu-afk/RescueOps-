import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    region: str
    incidents_table: str
    ambulances_table: str
    dispatch_queue: str
    reports_bucket: str
    ambulance_speed_kmh: float
    retry_delay_seconds: int
    poll_wait_seconds: int
    metrics_port: int
    log_level: str


def load_settings() -> Settings:
    return Settings(
        region=os.getenv("AWS_REGION", "us-east-1"),
        incidents_table=os.getenv("INCIDENTS_TABLE", "rescueops-incidents"),
        ambulances_table=os.getenv("AMBULANCES_TABLE", "rescueops-ambulances"),
        dispatch_queue=os.getenv("DISPATCH_QUEUE", "rescueops-dispatch-requests"),
        reports_bucket=os.getenv("REPORTS_BUCKET", "rescueops-dispatch-reports"),
        ambulance_speed_kmh=float(os.getenv("AMBULANCE_SPEED_KMH", "40")),
        retry_delay_seconds=int(os.getenv("RETRY_DELAY_SECONDS", "15")),
        poll_wait_seconds=int(os.getenv("POLL_WAIT_SECONDS", "10")),
        metrics_port=int(os.getenv("METRICS_PORT", "9100")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
