import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from .config import load_settings
from .logs import configure_logging
from .models import Ambulance, AmbulanceIn, Incident, IncidentIn
from .store import Store

log = logging.getLogger("dispatch-api")

REQUESTS = Counter("http_requests_total", "HTTP requests served", ["method", "route", "status"])
LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency", ["method", "route"])
INCIDENTS = Counter("rescueops_incidents_reported_total", "Incidents reported", ["severity"])


def _now() -> str:
    return datetime.now(UTC).isoformat()


def create_app() -> FastAPI:
    settings = load_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = Store(settings)
        yield

    app = FastAPI(title="RescueOps Dispatch API", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def observe(request: Request, call_next):
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            path = route.path if route else "unmatched"
            REQUESTS.labels(request.method, path, str(status)).inc()
            LATENCY.labels(request.method, path).observe(time.perf_counter() - start)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(request: Request):
        try:
            request.app.state.store.ping()
        except Exception:
            log.exception("readiness check failed")
            raise HTTPException(status_code=503, detail="dependencies unavailable") from None
        return {"status": "ready"}

    @app.get("/metrics")
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/incidents", status_code=202, response_model=Incident)
    def report_incident(body: IncidentIn, request: Request):
        incident = {
            **body.model_dump(),
            "incident_id": str(uuid.uuid4()),
            "status": "PENDING",
            "created_at": _now(),
        }
        request.app.state.store.create_incident(incident)
        INCIDENTS.labels(str(body.severity)).inc()
        # Caller phone is PII and deliberately kept out of logs.
        fields = {"incident_id": incident["incident_id"], "severity": body.severity}
        log.info("incident reported", extra={"fields": fields})
        return incident

    @app.get("/v1/incidents/{incident_id}", response_model=Incident)
    def get_incident(incident_id: str, request: Request):
        incident = request.app.state.store.get_incident(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="incident not found")
        return incident

    @app.post("/v1/ambulances", status_code=201, response_model=Ambulance)
    def register_ambulance(body: AmbulanceIn, request: Request):
        ambulance = {**body.model_dump(), "status": "AVAILABLE", "updated_at": _now()}
        request.app.state.store.put_ambulance(ambulance)
        log.info("ambulance available", extra={"fields": {"ambulance_id": body.ambulance_id}})
        return ambulance

    @app.get("/v1/ambulances", response_model=list[Ambulance])
    def list_ambulances(request: Request):
        return request.app.state.store.list_ambulances()

    return app


app = create_app()
