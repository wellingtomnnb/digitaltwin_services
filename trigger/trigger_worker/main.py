from __future__ import annotations

import json
import logging
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from trigger_worker.config import Settings
from trigger_worker.firebase import (
    FirebaseClient,
    prediction_payload_from_record,
    utc_now_iso,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("digitaltwin-trigger")


class PredictorClient:
    """Cliente HTTP interno para consumir o servico `/predict`."""

    def __init__(self, predictor_url: str, horizon_steps: int) -> None:
        self.predictor_url = predictor_url
        self.evaluate_url = (
            predictor_url.rsplit("/predict", 1)[0] + "/evaluate"
            if predictor_url.endswith("/predict")
            else predictor_url.rstrip("/") + "/evaluate"
        )
        self.default_horizon_steps = horizon_steps

    def predict(self, payload: dict[str, object], horizon_steps: int) -> dict[str, object]:
        """Chama a API de predicao e devolve o JSON de resposta."""
        url = f"{self.predictor_url}?{urlencode({'horizon_steps': horizon_steps})}"
        return self._post_json(url, payload)

    def evaluate(self, payload: dict[str, object], horizon_steps: int) -> dict[str, object]:
        """Chama a API de avaliacao e devolve o JSON de resposta."""
        url = f"{self.evaluate_url}?{urlencode({'horizon_steps': horizon_steps})}"
        return self._post_json(url, payload)

    def _post_json(self, url: str, payload: dict[str, object]) -> dict[str, object]:
        """Executa uma chamada POST e converte o corpo em JSON."""
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=body,
            method="POST",
            headers={
                "accept": "application/json",
                "Content-Type": "application/json",
            },
        )

        with urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")

        return json.loads(raw)


class FirebasePredictionTrigger:
    """Processo continuo que preenche previsoes em novos registros do Firebase."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.firebase = FirebaseClient(settings.firebase_host, settings.firebase_collection)
        self.predictor = PredictorClient(settings.predictor_url, settings.horizon_steps)
        self._last_horizon_steps = settings.horizon_steps

    def run_forever(self) -> None:
        """Mantem o trigger ativo, processando novos registros em ciclos curtos."""
        logger.info(
            "Trigger iniciado: collection=%s horizon_steps=%s poll_interval=%ss",
            self.settings.firebase_collection,
            self._last_horizon_steps,
            self.settings.poll_interval_seconds,
        )

        while True:
            try:
                processed = self.process_once()
                if processed:
                    logger.info("Registros enriquecidos neste ciclo: %s", processed)
            except Exception:
                logger.exception("Falha inesperada no ciclo do trigger")
            time.sleep(self.settings.poll_interval_seconds)

    def process_once(self) -> int:
        """Executa uma varredura curta nos ultimos registros do Firebase."""
        processed = 0
        records = self.firebase.fetch_latest(self.settings.fetch_limit)
        horizon_steps = self._resolve_horizon_steps()
        pending_predictions: list[tuple[str, dict[str, object], dict[str, object]]] = []
        pending_evaluations: list[tuple[str, dict[str, object], dict[str, object]]] = []

        for firebase_key, record in records:
            payload = prediction_payload_from_record(firebase_key, record)
            if payload is None:
                logger.warning("Registro ignorado por campos incompletos: %s", firebase_key)
                continue

            prediction = record.get(self.settings.prediction_field)
            if not isinstance(prediction, dict):
                pending_predictions.append((firebase_key, record, payload))
                continue

            if "rmse" in prediction and "actual_temperature" in prediction:
                continue

            pending_evaluations.append((firebase_key, record, payload))

        # Prioriza registros novos sem previsao para que o Firebase fique atualizado
        # o mais cedo possivel; as avaliacoes de registros antigos ficam por ultimo.
        for firebase_key, record, payload in reversed(pending_predictions):
            try:
                prediction = self.predictor.predict(payload, horizon_steps)
            except HTTPError as exc:
                detail = exc.read().decode("utf-8")
                logger.warning("Predicao recusada para %s: HTTP %s %s", firebase_key, exc.code, detail)
                continue
            except URLError as exc:
                logger.warning("Predictor indisponivel: %s", exc)
                break

            self.firebase.patch_record(
                firebase_key,
                {
                    self.settings.prediction_field: {
                        **prediction,
                        "generated_at": utc_now_iso(),
                        "source": "trigger",
                    }
                },
            )
            processed += 1

        for firebase_key, record, payload in pending_evaluations:
            prediction = record.get(self.settings.prediction_field)
            stored_horizon_steps = prediction.get("horizon_steps") or horizon_steps
            try:
                evaluation = self.predictor.evaluate(payload, int(stored_horizon_steps))
            except HTTPError as exc:
                if exc.code in {400, 404}:
                    continue
                detail = exc.read().decode("utf-8")
                logger.warning("Avaliacao recusada para %s: HTTP %s %s", firebase_key, exc.code, detail)
                continue
            except URLError as exc:
                logger.warning("Predictor indisponivel na avaliacao: %s", exc)
                break

            merged_prediction = {
                **prediction,
                **evaluation,
                "evaluated_at": utc_now_iso(),
                "source": prediction.get("source", "trigger"),
            }
            self.firebase.patch_record(
                firebase_key,
                {
                    self.settings.prediction_field: merged_prediction,
                },
            )
            processed += 1

        return processed

    def _resolve_horizon_steps(self) -> int:
        """Le o horizonte dinamico salvo pelo painel, mantendo fallback seguro."""
        try:
            config = self.firebase.get_path(self.settings.runtime_config_path)
        except Exception as exc:
            logger.warning("Nao foi possivel ler config dinamica, usando default: %s", exc)
            config = None

        raw_value = config.get("horizon_steps") if config else None

        try:
            horizon_steps = int(raw_value)
        except (TypeError, ValueError):
            horizon_steps = self.settings.horizon_steps

        horizon_steps = max(1, horizon_steps)
        if horizon_steps != self._last_horizon_steps:
            logger.info("Novo horizon_steps aplicado para previsoes futuras: %s", horizon_steps)
            self._last_horizon_steps = horizon_steps
        return horizon_steps


def main() -> None:
    settings = Settings.from_env()
    FirebasePredictionTrigger(settings).run_forever()


if __name__ == "__main__":
    main()
