from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class FirebaseClient:
    """Cliente REST minimo para ler e atualizar registros no Realtime Database."""

    def __init__(self, host: str, collection: str) -> None:
        self.host = host.rstrip("/")
        self.collection = collection.strip("/")

    def fetch_latest(self, limit: int) -> list[tuple[str, dict[str, object]]]:
        """Busca os ultimos registros ordenados pela chave do Firebase."""
        base_url = f"{self.host}/{self.collection}.json"
        params = {
            "orderBy": '"$key"',
            "limitToLast": str(max(1, limit)),
        }
        url = f"{base_url}?{urlencode(params, quote_via=quote)}"

        with urlopen(url, timeout=10) as response:
            raw = response.read().decode("utf-8")

        payload = json.loads(raw) if raw else None
        if not isinstance(payload, dict):
            return []

        records: list[tuple[str, dict[str, object]]] = []
        for key, value in sorted(payload.items()):
            if isinstance(value, dict):
                records.append((key, value))
        return records

    def patch_record(self, key: str, payload: dict[str, object]) -> None:
        """Atualiza apenas os campos derivados, preservando os dados coletados."""
        url = f"{self.host}/{self.collection}/{quote(key, safe='')}.json"
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=body,
            method="PATCH",
            headers={"Content-Type": "application/json"},
        )

        with urlopen(request, timeout=10) as response:
            response.read()


def timestamp_from_key(firebase_key: str) -> str:
    """Converte a chave `YYYY-MM-DD_HH-MM-SS` para timestamp legivel."""
    if "_" not in firebase_key:
        return firebase_key

    date_part, time_part = firebase_key.split("_", maxsplit=1)
    return f"{date_part} {time_part.replace('-', ':')}"


def prediction_payload_from_record(
    firebase_key: str,
    record: dict[str, object],
) -> dict[str, object] | None:
    """Monta o body esperado por `/predict` a partir de um registro bruto."""
    required_fields = ("ds18b201", "ds18b202", "mosfet", "setpoint")
    if any(field not in record for field in required_fields):
        return None

    timestamp = record.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp:
        timestamp = timestamp_from_key(firebase_key)

    return {
        "ds18b201": record["ds18b201"],
        "ds18b202": record["ds18b202"],
        "mosfet": record["mosfet"],
        "setpoint": record["setpoint"],
        "timestamp": timestamp,
    }


def utc_now_iso() -> str:
    """Timestamp UTC usado para auditoria da previsao gravada."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
