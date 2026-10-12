import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    region: str
    incidents_table: str
    ambulances_table: str
    dispatch_queue: str
    log_level: str


def load_settings() -> Settings:
    return Settings(
        region=os.getenv("AWS_REGION", "us-east-1"),
        incidents_table=os.getenv("INCIDENTS_TABLE", "rescueops-incidents"),
        ambulances_table=os.getenv("AMBULANCES_TABLE", "rescueops-ambulances"),
        dispatch_queue=os.getenv("DISPATCH_QUEUE", "rescueops-dispatch-requests"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
