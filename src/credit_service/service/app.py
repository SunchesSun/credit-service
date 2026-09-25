import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from credit_service import db
from credit_service.config import settings


class Features(BaseModel):
    model_config = {"extra": "forbid", "allow_inf_nan": False, "strict": True}
    age: int = Field(gt=0, lt=120)
    sex: Literal["female", "male"]
    job: int = Field(ge=0, le=3)
    housing: Literal["free", "own", "rent"]
    saving_accounts: Literal["little", "moderate", "quite rich", "rich"] | None = None
    checking_account: Literal["little", "moderate", "rich"] | None = None
    credit_amount: float = Field(gt=0)
    duration: int = Field(gt=0)
    purpose: Literal["business", "car", "domestic appliances", "education",
                      "furniture/equipment", "radio/TV", "repairs", "vacation/others"]


class Prediction(BaseModel):
    score: float = Field(ge=0, le=1)
    is_bad_risk: bool
    model_version: str
    request_id: uuid.UUID
    latency_ms: float = Field(ge=0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bundle = joblib.load(settings.model_path)
    app.state.pipeline = bundle["pipeline"]
    app.state.meta = bundle["metadata"]
    app.state.version = bundle["metadata"]["model_version"]

    db.init()

    try:
        yield
    finally:
        app.state.pipeline = None


app = FastAPI(title="credit-service", version="1.0", lifespan=lifespan)
logger = logging.getLogger(__name__)


@app.middleware("http")
async def audit(request: Request, call_next):
    if request.url.path != "/v1/predict" or request.method != "POST":
        return await call_next(request)
    started = time.perf_counter()
    request.state.request_id = str(uuid.uuid4())
    request.state.prediction = None
    raw = await request.body()
    try:
        features = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        features = {"invalid_body": raw.decode("utf-8", errors="replace")}
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Prediction failed")
        response = JSONResponse({"detail": "Prediction failed"}, status_code=500)
    latency = (time.perf_counter() - started) * 1000
    try:
        await run_in_threadpool(
            db.save_prediction,
            request.state.request_id,
            features,
            request.state.prediction,
            app.state.meta["model_version"],
            latency,
            response.status_code,
        )
    except Exception:
        logger.exception("Cannot persist prediction %s", request.state.request_id)
        response = JSONResponse({"detail": "Prediction log unavailable"}, status_code=503)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.get("/health")
def health():
    return {"status": "ok", "model_version": getattr(app.state, "version", "unknown")}


@app.get("/ready")
def ready():
    if getattr(app.state, "pipeline", None) is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"status": "ready"}


@app.post("/v1/predict")
def predict(x: Features, request: Request) -> Prediction:
    t0 = time.perf_counter()
    ready()

    frame = pd.DataFrame([x.model_dump()], columns = app.state.meta["features"]).replace({None: np.nan})
    score = float(app.state.pipeline.predict_proba(frame)[0, 1])
    prediction = {"score" : score, "is_bad_risk" : score >= app.state.meta["threshold"]}
    latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    request.state.prediction = prediction
    return Prediction(**prediction,
                    model_version=app.state.version,
                    request_id=request.state.request_id,
                    latency_ms=latency_ms
    )
