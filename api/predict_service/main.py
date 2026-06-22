from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request

from app.schemas.prediction import PredictionRequest, PredictionResponse
from app.services.predictor import (
    DigitalTwinPredictor,
    InsufficientHistoryError,
    PredictorError,
    TimestampNotFoundError,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    predictor = DigitalTwinPredictor()
    predictor.load()
    app.state.predictor = predictor
    yield


app = FastAPI(
    title="Digital Twin Predict API",
    version="1.0",
    description="Serviço isolado de predição de temperatura.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/predict", response_model=PredictionResponse)
def predict(
    request_body: PredictionRequest,
    request: Request,
    horizon_steps: int = Query(
        default=10,
        ge=1,
        description="Quantidade de passos à frente para a previsão",
    ),
) -> PredictionResponse:
    predictor = request.app.state.predictor

    try:
        return predictor.predict(request_body, horizon_steps)
    except TimestampNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InsufficientHistoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PredictorError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

