from typing import Literal

from pydantic import BaseModel, Field


class IncidentIn(BaseModel):
    caller_phone: str = Field(pattern=r"^\+?[0-9]{7,15}$")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    severity: int = Field(ge=1, le=5, description="1 = minor, 5 = life-threatening")
    description: str = Field(default="", max_length=500)


class Incident(IncidentIn):
    incident_id: str
    status: Literal["PENDING", "DISPATCHED"]
    created_at: str
    ambulance_id: str | None = None
    distance_km: float | None = None
    eta_minutes: float | None = None
    dispatched_at: str | None = None


class AmbulanceIn(BaseModel):
    ambulance_id: str = Field(pattern=r"^[A-Za-z0-9-]{3,32}$")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class Ambulance(AmbulanceIn):
    status: Literal["AVAILABLE", "DISPATCHED"]
    updated_at: str
    incident_id: str | None = None
