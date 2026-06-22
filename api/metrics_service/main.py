from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Query

from metrics_service.calculator import MetricsCalculator


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa o calculador e aquece o cache antes de aceitar requisições."""
    calculator = MetricsCalculator()
    calculator.load()
    app.state.calculator = calculator
    yield


app = FastAPI(
    title="Digital Twin Metrics API",
    version="1.0",
    description="Serviço isolado de métricas do controlador.",
    docs_url='/tests',
    redoc_url=None,
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    """Healthcheck simples para monitoração e orquestração."""
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, object]:
    """Mostra as rotas principais quando a raiz do servico for acessada."""
    return {
        "service": "Digital Twin Metrics API",
        "status": "ok",
        "routes": {
            "health": "GET /health",
            "summary": "GET /metrics/summary",
            "control": "GET /metrics/control",
            "process": "GET /metrics/process",
            "timing": "GET /metrics/timing",
            "duty_cycle": "GET /metrics/duty-cycle",
            "dashboard": "GET /metrics/dashboard",
        },
    }


@app.get("/metrics/summary")
def summary(
    timestamp: datetime | None = Query(default=None, description="Timestamp de referência"),
    lookback_samples: int = Query(default=20, ge=2, le=500, description="Quantidade de amostras de histórico"),
) -> dict[str, object]:
    """Retorna um resumo amplo com os principais indicadores do controlador."""
    return app.state.calculator.summary(timestamp=timestamp, lookback_samples=lookback_samples)


@app.get("/metrics/control")
def control(
    timestamp: datetime | None = Query(default=None, description="Timestamp de referência"),
    lookback_samples: int = Query(default=20, ge=2, le=500, description="Quantidade de amostras de histórico"),
) -> dict[str, object]:
    """Expõe métricas focadas em controle térmico e estado operacional."""
    return app.state.calculator.control(timestamp=timestamp, lookback_samples=lookback_samples)


@app.get("/metrics/process")
def process(
    timestamp: datetime | None = Query(default=None, description="Timestamp de referência"),
    lookback_samples: int = Query(default=20, ge=2, le=500, description="Quantidade de amostras de histórico"),
) -> dict[str, object]:
    """Expõe métricas de processo para inspeção rápida no painel."""
    return app.state.calculator.process(timestamp=timestamp, lookback_samples=lookback_samples)


@app.get("/metrics/timing")
def timing(
    timestamp: datetime | None = Query(default=None, description="Timestamp de referência"),
    lookback_samples: int = Query(default=20, ge=2, le=500, description="Quantidade de amostras de histórico"),
) -> dict[str, object]:
    """Retorna métricas ligadas ao tempo do controle e comutação."""
    return app.state.calculator.timing(timestamp=timestamp, lookback_samples=lookback_samples)


@app.get("/metrics/duty-cycle")
def duty_cycle(
    timestamp: datetime | None = Query(default=None, description="Timestamp de referência"),
    lookback_samples: int = Query(default=20, ge=2, le=500, description="Quantidade de amostras de histórico"),
) -> dict[str, object]:
    """Retorna o conjunto mínimo necessário para acompanhar o duty cycle."""
    return app.state.calculator.duty_cycle(timestamp=timestamp, lookback_samples=lookback_samples)


@app.get("/metrics/dashboard")
def dashboard(
    timestamp: datetime | None = Query(default=None, description="Timestamp de referência"),
    lookback_samples: int = Query(default=20, ge=2, le=500, description="Quantidade de amostras de histórico"),
) -> dict[str, object]:
    """Entrega um payload já pronto para Streamlit e outros consumidores visuais."""
    return app.state.calculator.dashboard(timestamp=timestamp, lookback_samples=lookback_samples)
