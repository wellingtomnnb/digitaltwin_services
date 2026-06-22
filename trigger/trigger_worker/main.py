from __future__ import annotations

import json
import logging
import time
from collections import deque
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
        self.horizon_steps = horizon_steps

    def predict(self, payload: dict[str, object]) -> dict[str, object]:
        """Chama a API de predicao e devolve o JSON de resposta."""
        url = f"{self.predictor_url}?{urlencode({'horizon_steps': self.horizon_steps})}"
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
        self._failed_keys: deque[str] = deque(maxlen=500)

    def run_forever(self) -> None:
        """Mantem o trigger ativo, processando novos registros em ciclos curtos."""
        logger.info(
            "Trigger iniciado: collection=%s horizon_steps=%s poll_interval=%ss",
            self.settings.firebase_collection,
            self.settings.horizon_steps,
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

        for firebase_key, record in records:
            if self.settings.prediction_field in record:
                continue
            if firebase_key in self._failed_keys:
                continue

            payload = prediction_payload_from_record(firebase_key, record)
            if payload is None:
                logger.warning("Registro ignorado por campos incompletos: %s", firebase_key)
                self._failed_keys.append(firebase_key)
                continue

            try:
                prediction = self.predictor.predict(payload)
            except HTTPError as exc:
                detail = exc.read().decode("utf-8")
                logger.warning("Predicao recusada para %s: HTTP %s %s", firebase_key, exc.code, detail)
                self._failed_keys.append(firebase_key)
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

        return processed


def main() -> None:
    settings = Settings.from_env()
    FirebasePredictionTrigger(settings).run_forever()


if __name__ == "__main__":
    main()
