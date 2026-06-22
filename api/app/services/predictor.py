from __future__ import annotations

import json
import pickle
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import urlopen

import joblib
import pandas as pd
from tensorflow.keras.models import load_model

from app.core.config import (
    MODEL_COLUMNS_PATH,
    MODEL_KERAS_PATH,
    FIREBASE_COLLECTION,
    FIREBASE_HOST,
    WINDOW_SIZE,
    X_SCALER_PATH,
    Y_SCALER_PATH,
)
from app.schemas.prediction import EvaluationResponse, PredictionRequest, PredictionResponse


class PredictorError(Exception):
    """Erro base para falhas na camada de predição."""
    pass


class TimestampNotFoundError(PredictorError):
    """Indica que o timestamp solicitado não existe no Firebase."""
    pass


class InsufficientHistoryError(PredictorError):
    """Indica que não há amostras anteriores suficientes para montar a janela."""
    pass


class InsufficientFutureDataError(PredictorError):
    """Indica que não há dados futuros suficientes para avaliação."""
    pass


@dataclass
class PredictionArtifacts:
    """Agrupa os artefatos necessários para executar uma predição."""

    model: object
    x_scaler: object
    y_scaler: object
    columns: list[str]
    step_seconds: int


class DigitalTwinPredictor:
    """Encapsula carregamento do modelo, preparo das features e inferência."""

    def __init__(self) -> None:
        self.artifacts: PredictionArtifacts | None = None
        self._firebase_cache: dict[tuple[str, str, int, int], tuple[float, pd.DataFrame]] = {}

    def load(self) -> None:
        """Carrega modelo, scalers e o passo temporal inferido no Firebase."""
        if self.artifacts is not None:
            return

        model_path = self._prepare_model_path()
        model = load_model(str(model_path), compile=False)

        x_scaler = joblib.load(X_SCALER_PATH)
        y_scaler = joblib.load(Y_SCALER_PATH)

        with MODEL_COLUMNS_PATH.open("rb") as file:
            columns = list(pickle.load(file))

        step_seconds = self._infer_step_seconds(self._fetch_records(limit_to_last=2, force=True))

        self.artifacts = PredictionArtifacts(
            model=model,
            x_scaler=x_scaler,
            y_scaler=y_scaler,
            columns=columns,
            step_seconds=step_seconds,
        )

    def predict(self, request: PredictionRequest, horizon_steps: int) -> PredictionResponse:
        """Executa a predição e devolve apenas o valor estimado."""
        predicted_temperature, predicted_timestamp = self._predict_core(request, horizon_steps)
        return PredictionResponse(
            predicted_temperature=predicted_temperature,
            reference_timestamp=pd.Timestamp(request.timestamp).to_pydatetime(),
            predicted_timestamp=predicted_timestamp,
            horizon_steps=horizon_steps,
            window_size=WINDOW_SIZE,
        )

    def evaluate(self, request: PredictionRequest, horizon_steps: int) -> EvaluationResponse:
        """Executa a predição e compara com o valor real disponível no Firebase."""
        predicted_temperature, predicted_timestamp = self._predict_core(request, horizon_steps)

        if self.artifacts is None:
            raise PredictorError("Predictor not loaded")

        timestamp = pd.Timestamp(request.timestamp)
        timestamp_key = self._firebase_key(timestamp)

        exact = self._fetch_records(
            start_at=timestamp_key,
            end_at=timestamp_key,
            limit_to_first=1,
        )
        if len(exact) == 0 or pd.Timestamp(exact.iloc[0]["timestamp"]) != timestamp:
            raise TimestampNotFoundError(
                "Timestamp not found in Firebase. "
                "The API needs this timestamp to compare against future values."
            )

        future = self._fetch_records(
            start_at=timestamp_key,
            limit_to_first=horizon_steps,
        )
        if len(future) < horizon_steps:
            raise InsufficientFutureDataError(
                f"Not enough future data after {timestamp} to compare against horizon {horizon_steps}."
            )

        if pd.Timestamp(future.iloc[0]["timestamp"]) != timestamp:
            raise TimestampNotFoundError(
                "Timestamp not found in Firebase. "
                "The API needs this timestamp to compare against future values."
            )

        actual_temperature = float(future.iloc[horizon_steps - 1]["ds18b201"])
        rmse = abs(predicted_temperature - actual_temperature)

        return EvaluationResponse(
            predicted_temperature=predicted_temperature,
            actual_temperature=actual_temperature,
            rmse=rmse,
            reference_timestamp=timestamp.to_pydatetime(),
            predicted_timestamp=predicted_timestamp,
            horizon_steps=horizon_steps,
            window_size=WINDOW_SIZE,
        )

    def _predict_core(self, request: PredictionRequest, horizon_steps: int) -> tuple[float, datetime]:
        """Prepara a janela, normaliza os dados e executa a inferência do modelo."""
        if self.artifacts is None:
            self.load()

        if self.artifacts is None:
            raise PredictorError("Predictor not loaded")

        timestamp = pd.Timestamp(request.timestamp)
        timestamp_key = self._firebase_key(timestamp)

        history = self._fetch_records(
            end_at=timestamp_key,
            limit_to_last=WINDOW_SIZE,
        )
        history = history[history["timestamp"] < timestamp].copy()
        history = history.tail(WINDOW_SIZE - 1).reset_index(drop=True)

        if len(history) < WINDOW_SIZE - 1:
            raise InsufficientHistoryError(
                f"Not enough history before {timestamp} to build a window of {WINDOW_SIZE} samples."
            )

        current_row = pd.DataFrame(
            [
                {
                    "timestamp": timestamp,
                    "ds18b201": request.ds18b201,
                    "ds18b202": request.ds18b202,
                    "mosfet": request.mosfet,
                    "setpoint": request.setpoint,
                }
            ]
        )

        window = pd.concat([history, current_row], ignore_index=True)
        features = window[self.artifacts.columns]

        scaled = self.artifacts.x_scaler.transform(features)
        scaled = scaled.reshape(1, WINDOW_SIZE, len(self.artifacts.columns))

        predicted_scaled = self.artifacts.model.predict(scaled, verbose=0)
        predicted_temperature = self.artifacts.y_scaler.inverse_transform(
            predicted_scaled.reshape(-1, 1)
        )[0][0]

        predicted_timestamp = pd.Timestamp(timestamp) + timedelta(
            seconds=self.artifacts.step_seconds * horizon_steps
        )
        return round(float(predicted_temperature), 2), predicted_timestamp.to_pydatetime()

    def _prepare_model_path(self) -> Path:
        """Escolhe o melhor artefato de modelo disponível em disco."""
        if MODEL_KERAS_PATH.exists():
            return MODEL_KERAS_PATH

        raise FileNotFoundError("No model artifact found. Expected .keras inside data/.")

    def _firebase_key(self, timestamp: datetime | pd.Timestamp | None) -> str | None:
        """Converte timestamp no formato usado como chave no Firebase."""
        if timestamp is None:
            return None
        ts = pd.Timestamp(timestamp)
        if pd.isna(ts):
            return None
        return ts.strftime("%Y-%m-%d_%H-%M-%S")

    def _fetch_records(
        self,
        *,
        start_at: str | None = None,
        end_at: str | None = None,
        limit_to_first: int | None = None,
        limit_to_last: int | None = None,
        force: bool = False,
    ) -> pd.DataFrame:
        """Busca registros do Firebase Realtime Database via REST."""
        if limit_to_first is None and limit_to_last is None and start_at is None and end_at is None:
            raise ValueError("At least one Firebase query constraint must be provided")

        cache_key = (
            start_at or "",
            end_at or "",
            int(limit_to_first or 0),
            int(limit_to_last or 0),
        )
        cached = self._firebase_cache.get(cache_key)
        now = time.monotonic()
        if not force and cached and now - cached[0] < 1.0:
            return cached[1].copy()

        base_url = f"{FIREBASE_HOST.rstrip('/')}/{FIREBASE_COLLECTION}.json"
        params: dict[str, str] = {"orderBy": '"$key"'}
        if start_at is not None:
            params["startAt"] = f'"{start_at}"'
        if end_at is not None:
            params["endAt"] = f'"{end_at}"'
        if limit_to_first is not None:
            params["limitToFirst"] = str(limit_to_first)
        if limit_to_last is not None:
            params["limitToLast"] = str(limit_to_last)

        url = f"{base_url}?{urlencode(params, quote_via=quote)}"
        with urlopen(url, timeout=10) as response:
            raw = response.read().decode("utf-8")

        payload = json.loads(raw) if raw else None
        frame = self._normalize_payload(payload)
        self._firebase_cache[cache_key] = (now, frame)
        return frame.copy()

    def _normalize_payload(self, payload: dict[str, object] | None) -> pd.DataFrame:
        """Converte o retorno do Firebase em uma tabela padronizada."""
        if not payload:
            return pd.DataFrame(
                columns=["timestamp", "ds18b201", "ds18b202", "mosfet", "setpoint"]
            )

        rows: list[dict[str, object]] = []
        for firebase_id, item in payload.items():
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["_firebase_id"] = firebase_id
            rows.append(row)

        if not rows:
            return pd.DataFrame(
                columns=["timestamp", "ds18b201", "ds18b202", "mosfet", "setpoint"]
            )

        frame = pd.DataFrame(rows)
        if "timestamp" not in frame.columns:
            frame["timestamp"] = frame["_firebase_id"].map(
                lambda value: pd.to_datetime(value, format="%Y-%m-%d_%H-%M-%S", errors="coerce")
                if isinstance(value, str)
                else pd.NaT
            )
        else:
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")

        for field in ("ds18b201", "ds18b202", "setpoint"):
            if field not in frame.columns:
                frame[field] = pd.NA
            frame[field] = pd.to_numeric(frame[field], errors="coerce")

        if "mosfet" not in frame.columns:
            frame["mosfet"] = 0
        frame["mosfet"] = pd.to_numeric(frame["mosfet"], errors="coerce").fillna(0).astype(int)

        frame = frame.dropna(subset=["timestamp", "ds18b201", "ds18b202", "setpoint"]).copy()
        frame = frame[(frame["ds18b201"] != -127.0) & (frame["ds18b202"] != -127.0)]
        frame = frame.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
        frame = frame.reset_index(drop=True)
        return frame

    @staticmethod
    def _infer_step_seconds(dataset: pd.DataFrame) -> int:
        """Infere o intervalo médio entre amostras do dataset."""
        diffs = dataset["timestamp"].diff().dropna().dt.total_seconds()
        if diffs.empty:
            return 1
        return int(round(diffs.mode().iloc[0] if not diffs.mode().empty else diffs.median()))
