from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Configuracoes do processo que enriquece registros do Firebase."""

    firebase_host: str
    firebase_collection: str
    predictor_url: str
    horizon_steps: int
    poll_interval_seconds: float
    fetch_limit: int
    prediction_field: str

    @classmethod
    def from_env(cls) -> "Settings":
        """Carrega configuracoes por variaveis de ambiente com defaults locais."""
        return cls(
            firebase_host=os.getenv(
                "FIREBASE_HOST",
                "https://digitaltwim-default-rtdb.firebaseio.com",
            ),
            firebase_collection=os.getenv(
                "FIREBASE_COLLECTION",
                "digital_twin_dinamico_rev1",
            ),
            predictor_url=os.getenv(
                "PREDICTOR_URL",
                "http://predictor:8000/predict",
            ),
            horizon_steps=int(os.getenv("HORIZON_STEPS", "10")),
            poll_interval_seconds=float(os.getenv("POLL_INTERVAL_SECONDS", "2")),
            fetch_limit=int(os.getenv("FETCH_LIMIT", "30")),
            prediction_field=os.getenv("PREDICTION_FIELD", "prediction"),
        )
