from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from urllib.parse import quote, urlencode
from urllib.request import urlopen

import numpy as np
import pandas as pd

from app.core.config import FIREBASE_COLLECTION, FIREBASE_HOST


@dataclass
class MetricsWindow:
    """Janela de dados usada para calcular métricas do controlador."""

    history: pd.DataFrame
    current: pd.Series


class MetricsCalculator:
    """Calcula métricas de operação a partir dos dados mais recentes do Firebase."""

    CYCLE_TIME_INITIAL_LOOKBACK = 300
    CYCLE_TIME_GROWTH_FACTOR = 1.4
    CYCLE_TIME_MAX_LOOKBACK = 5_000

    def __init__(self) -> None:
        self._window_cache: dict[tuple[str, int], tuple[float, pd.DataFrame]] = {}

    def load(self) -> None:
        """Pré-aquece o cache com a janela mais recente."""
        self._fetch_window(None, 20, force=True)

    def summary(
        self,
        timestamp: datetime | None = None,
        lookback_samples: int = 20,
    ) -> dict[str, object]:
        window = self._resolve_window(timestamp, lookback_samples)
        return self._build_summary(window, lookback_samples)

    def _build_summary(self, window: MetricsWindow, lookback_samples: int) -> dict[str, object]:
        """Monta o resumo consolidado com todas as métricas derivadas da janela."""
        history = window.history
        current = window.current
        erro_controle = float(current["setpoint"] - current["ds18b201"])
        diff_sensores = float(current["ds18b201"] - current["ds18b202"])
        taxa_variacao = self._taxa_variacao(history)
        tendencia = self._tendencia(history)
        tempo_mosfet_ligado = self._tempo_mosfet_ligado(history)
        duty_cycle = self._duty_cycle(history)
        tempo_desde_troca_setpoint = self._tempo_desde_troca_setpoint(history)
        idade_setpoint = tempo_desde_troca_setpoint
        estado_controle = self._estado_controle(current, erro_controle)
        sensor_health = self._sensor_health(history)
        stability_score = self._stability_score(history, erro_controle, taxa_variacao)
        overshoot, undershoot = self._overshoot_undershoot(history, float(current["setpoint"]))
        cycle_time = self._cycle_time_with_contingency(history)

        return {
            "timestamp": current["timestamp"].isoformat(),
            "ds18b201": float(current["ds18b201"]),
            "ds18b202": float(current["ds18b202"]),
            "mosfet": int(current["mosfet"]),
            "setpoint": float(current["setpoint"]),
            "erro_controle": erro_controle,
            "diff_sensores": diff_sensores,
            "tendencia": tendencia,
            "taxa_variacao": taxa_variacao,
            "tempo_mosfet_ligado": tempo_mosfet_ligado,
            "tempo_desde_troca_setpoint": tempo_desde_troca_setpoint,
            "idade_setpoint": idade_setpoint,
            "estado_controle": estado_controle,
            "sensor_health": sensor_health,
            "stability_score": stability_score,
            "overshoot": overshoot,
            "undershoot": undershoot,
            "cycle_time": cycle_time,
            "duty_cycle": duty_cycle,
            "lookback_samples": lookback_samples,
        }

    def control(self, timestamp: datetime | None = None, lookback_samples: int = 20) -> dict[str, object]:
        """Retorna apenas os indicadores ligados ao controle térmico."""
        data = self.summary(timestamp, lookback_samples)
        return {
            "timestamp": data["timestamp"],
            "setpoint": data["setpoint"],
            "ds18b201": data["ds18b201"],
            "erro_controle": data["erro_controle"],
            "estado_controle": data["estado_controle"],
        }

    def process(self, timestamp: datetime | None = None, lookback_samples: int = 20) -> dict[str, object]:
        """Retorna os indicadores mais úteis para análise de processo."""
        data = self.summary(timestamp, lookback_samples)
        return {
            "timestamp": data["timestamp"],
            "diff_sensores": data["diff_sensores"],
            "tendencia": data["tendencia"],
            "taxa_variacao": data["taxa_variacao"],
            "stability_score": data["stability_score"],
            "overshoot": data["overshoot"],
            "undershoot": data["undershoot"],
            "sensor_health": data["sensor_health"],
        }

    def timing(self, timestamp: datetime | None = None, lookback_samples: int = 20) -> dict[str, object]:
        """Retorna métricas de temporização do acionamento e do setpoint."""
        data = self.summary(timestamp, lookback_samples)
        return {
            "timestamp": data["timestamp"],
            "tempo_mosfet_ligado": data["tempo_mosfet_ligado"],
            "tempo_desde_troca_setpoint": data["tempo_desde_troca_setpoint"],
            "idade_setpoint": data["idade_setpoint"],
            "cycle_time": data["cycle_time"],
        }

    def duty_cycle(self, timestamp: datetime | None = None, lookback_samples: int = 20) -> dict[str, object]:
        """Retorna a visão resumida necessária para monitorar duty cycle."""
        data = self.summary(timestamp, lookback_samples)
        return {
            "timestamp": data["timestamp"],
            "tempo_mosfet_ligado": data["tempo_mosfet_ligado"],
            "duty_cycle": data["duty_cycle"],
            "cycle_time": data["cycle_time"],
            "lookback_samples": data["lookback_samples"],
        }

    def dashboard(self, timestamp: datetime | None = None, lookback_samples: int = 20) -> dict[str, object]:
        """Entrega um payload pronto para consumo por dashboards e Streamlit."""
        window = self._resolve_window(timestamp, lookback_samples)
        summary = self._build_summary(window, lookback_samples)
        history = window.history

        cards = [
            self._card("duty_cycle", "Duty cycle", summary["duty_cycle"], "%", 2),
            self._card("erro_controle", "Erro de controle", summary["erro_controle"], "°C", 2),
            self._card("diff_sensores", "Diferença entre sensores", summary["diff_sensores"], "°C", 2),
            self._card("stability_score", "Estabilidade", summary["stability_score"], "pts", 1),
            self._card("tempo_mosfet_ligado", "MOSFET ligado", summary["tempo_mosfet_ligado"], "s", 1),
            self._card("cycle_time", "Cycle time", summary["cycle_time"], "s", 1),
            self._card("overshoot", "Overshoot", summary["overshoot"], "°C", 2),
            self._card("undershoot", "Undershoot", summary["undershoot"], "°C", 2),
        ]

        chart = {
            "temperaturas": {
                "titulo": "Temperaturas",
                "timestamp": history["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist(),
                "resistor": history["ds18b201"].astype(float).round(3).tolist(),
                "ambiente": history["ds18b202"].astype(float).round(3).tolist(),
                "setpoint": history["setpoint"].astype(float).round(3).tolist(),
            },
            "atuacao": {
                "titulo": "Atuação",
                "timestamp": history["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist(),
                "mosfet": history["mosfet"].astype(int).tolist(),
            },
            "controle": {
                "titulo": "Controle",
                "timestamp": history["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist(),
                "erro_controle": (history["setpoint"] - history["ds18b201"]).astype(float).round(3).tolist(),
            },
        }

        return {
            "titulo": "Painel do controlador",
            "timestamp_base": summary["timestamp"],
            "janela_amostras": lookback_samples,
            "cartoes": cards,
            "indicadores": {
                "erro_controle": summary["erro_controle"],
                "diff_sensores": summary["diff_sensores"],
                "tendencia": summary["tendencia"],
                "taxa_variacao": summary["taxa_variacao"],
                "tempo_mosfet_ligado": summary["tempo_mosfet_ligado"],
                "tempo_desde_troca_setpoint": summary["tempo_desde_troca_setpoint"],
                "idade_setpoint": summary["idade_setpoint"],
                "estado_controle": summary["estado_controle"],
                "sensor_health": summary["sensor_health"],
                "stability_score": summary["stability_score"],
                "overshoot": summary["overshoot"],
                "undershoot": summary["undershoot"],
                "cycle_time": summary["cycle_time"],
                "duty_cycle": summary["duty_cycle"],
            },
            "graficos": chart,
        }

    def _resolve_window(
        self,
        timestamp: datetime | None,
        lookback_samples: int,
    ) -> MetricsWindow:
        """Carrega a janela de dados e separa o último ponto como amostra atual."""
        dataset = self._fetch_window(timestamp, lookback_samples)
        if len(dataset) == 0:
            raise RuntimeError("Dataset not available")

        history = dataset.reset_index(drop=True)
        current = history.iloc[-1]
        return MetricsWindow(history=history, current=current)

    def _firebase_key(self, timestamp: datetime | pd.Timestamp | None) -> str | None:
        """Converte um timestamp para a chave usada pelos nós do Firebase."""
        if timestamp is None:
            return None
        ts = pd.Timestamp(timestamp)
        if pd.isna(ts):
            return None
        return ts.strftime("%Y-%m-%d_%H-%M-%S")

    def _fetch_window(
        self,
        timestamp: datetime | None,
        lookback_samples: int,
        force: bool = False,
    ) -> pd.DataFrame:
        """Busca a janela solicitada diretamente no Realtime Database via REST."""
        lookback_samples = max(2, int(lookback_samples))
        firebase_key = self._firebase_key(timestamp)
        cache_key = (firebase_key or "__latest__", lookback_samples)
        cached = self._window_cache.get(cache_key)
        now = time.monotonic()
        if not force and cached and now - cached[0] < 1.0:
            return cached[1].copy()

        base_url = f"{FIREBASE_HOST.rstrip('/')}/{FIREBASE_COLLECTION}.json"
        # A API do Realtime Database exige orderBy com $key entre aspas.
        params: dict[str, str] = {
            "orderBy": '"$key"',
            "limitToLast": str(lookback_samples + 1),
        }
        if firebase_key is not None:
            params["endAt"] = f'"{firebase_key}"'

        url = f"{base_url}?{urlencode(params, quote_via=quote)}"
        with urlopen(url, timeout=10) as response:
            raw = response.read().decode("utf-8")

        payload = json.loads(raw) if raw else None
        if not payload:
            empty = pd.DataFrame(columns=["timestamp", "ds18b201", "ds18b202", "mosfet", "setpoint"])
            self._window_cache[cache_key] = (now, empty)
            return empty.copy()

        rows: list[dict[str, object]] = []
        for firebase_id, item in payload.items():
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["_firebase_id"] = firebase_id
            rows.append(row)

        if not rows:
            empty = pd.DataFrame(columns=["timestamp", "ds18b201", "ds18b202", "mosfet", "setpoint"])
            self._window_cache[cache_key] = (now, empty)
            return empty.copy()

        frame = pd.DataFrame(rows)
        if "timestamp" not in frame.columns:
            frame["timestamp"] = pd.NaT
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")

        for field in ("ds18b201", "ds18b202", "setpoint"):
            if field not in frame.columns:
                frame[field] = np.nan
            frame[field] = pd.to_numeric(frame[field], errors="coerce")

        if "mosfet" not in frame.columns:
            frame["mosfet"] = 0
        frame["mosfet"] = pd.to_numeric(frame["mosfet"], errors="coerce").fillna(0).astype(int)

        frame = frame.dropna(subset=["timestamp", "ds18b201", "ds18b202", "setpoint"]).copy()
        frame = frame[(frame["ds18b201"] != -127.0) & (frame["ds18b202"] != -127.0)]
        frame = frame.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
        frame = frame.reset_index(drop=True)

        self._window_cache[cache_key] = (now, frame)
        return frame.copy()

    @staticmethod
    def _duration_seconds(start: pd.Timestamp, end: pd.Timestamp) -> float:
        """Calcula a diferença entre dois timestamps em segundos."""
        return float((end - start).total_seconds())

    @staticmethod
    def _format_value(value: object, decimals: int) -> object:
        """Normaliza valores numéricos para resposta amigável ao cliente."""
        if value is None:
            return None
        if isinstance(value, (float, np.floating)):
            return round(float(value), decimals)
        if isinstance(value, (int, np.integer)):
            return int(value)
        return value

    def _card(self, chave: str, titulo: str, valor: object, unidade: str, decimals: int) -> dict[str, object]:
        """Padroniza a estrutura dos cartões do dashboard."""
        formatted = self._format_value(valor, decimals)
        return {
            "chave": chave,
            "titulo": titulo,
            "valor": formatted,
            "unidade": unidade,
            "texto": f"{formatted} {unidade}" if formatted is not None else "n/d",
        }

    def _series(self, history: pd.DataFrame, fields: list[str]) -> dict[str, object]:
        """Serializa colunas do histórico em um formato simples para gráficos."""
        series = {"timestamp": history["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist()}
        for field in fields:
            if field == "mosfet":
                series["mosfet"] = history[field].astype(int).tolist()
            else:
                series[field] = history[field].astype(float).round(3).tolist()
        return series

    def _taxa_variacao(self, history: pd.DataFrame) -> float:
        """Calcula a taxa de variação do sensor principal ao longo da janela."""
        if len(history) < 2:
            return 0.0
        first = history.iloc[0]
        last = history.iloc[-1]
        elapsed = self._duration_seconds(first["timestamp"], last["timestamp"])
        if elapsed <= 0:
            return 0.0
        return float((last["ds18b201"] - first["ds18b201"]) / elapsed)

    def _tendencia(self, history: pd.DataFrame) -> str:
        """Classifica a tendência da temperatura principal como subindo, descendo ou estável."""
        if len(history) < 3:
            return "estavel"
        x = (history["timestamp"] - history["timestamp"].iloc[0]).dt.total_seconds().to_numpy()
        y = history["ds18b201"].to_numpy()
        slope = float(np.polyfit(x, y, 1)[0]) if len(np.unique(x)) > 1 else 0.0
        if slope > 0.005:
            return "subindo"
        if slope < -0.005:
            return "descendo"
        return "estavel"

    def _tempo_mosfet_ligado(self, history: pd.DataFrame) -> float:
        """Soma o tempo em que o MOSFET permaneceu acionado dentro da janela."""
        if len(history) < 2:
            return 0.0
        on_time = 0.0
        for idx in range(len(history) - 1):
            current = history.iloc[idx]
            nxt = history.iloc[idx + 1]
            if int(current["mosfet"]) == 1:
                on_time += self._duration_seconds(current["timestamp"], nxt["timestamp"])
        return float(on_time)

    def _duty_cycle(self, history: pd.DataFrame) -> float:
        """Calcula o duty cycle percentual com base no tempo ligado e no tempo total."""
        if len(history) < 2:
            return 0.0
        total_time = self._duration_seconds(history.iloc[0]["timestamp"], history.iloc[-1]["timestamp"])
        if total_time <= 0:
            return 0.0
        on_time = self._tempo_mosfet_ligado(history)
        return float((on_time / total_time) * 100.0)

    def _tempo_desde_troca_setpoint(self, history: pd.DataFrame) -> float:
        """Mede há quanto tempo o setpoint permanece sem alteração."""
        if len(history) < 2:
            return 0.0
        setpoint_series = history["setpoint"].to_numpy()
        change_points = np.where(setpoint_series[1:] != setpoint_series[:-1])[0]
        if len(change_points) == 0:
            start_ts = history.iloc[0]["timestamp"]
        else:
            start_ts = history.iloc[int(change_points[-1]) + 1]["timestamp"]
        return self._duration_seconds(start_ts, history.iloc[-1]["timestamp"])

    def _estado_controle(self, current: pd.Series, erro_controle: float) -> str:
        """Resume o estado do controle térmico em uma etiqueta legível."""
        mosfet = int(current["mosfet"])
        hysteresis = 1.0
        if mosfet == 1:
            return "aquecendo" if erro_controle > -hysteresis else "saturado"
        if abs(erro_controle) <= hysteresis:
            return "estavel"
        if erro_controle > hysteresis:
            return "aguardando_aquecimento"
        return "acima_do_setpoint"

    def _sensor_health(self, history: pd.DataFrame) -> dict[str, object]:
        """Avalia se os sensores parecem saudáveis com base em faixa, ruído e discrepância."""
        current = history.iloc[-1]
        reasons: list[str] = []
        score = 100.0

        for field in ("ds18b201", "ds18b202"):
            value = float(current[field])
            if not np.isfinite(value):
                reasons.append(f"{field} invalido")
                score -= 60
            if value < -20 or value > 125:
                reasons.append(f"{field} fora da faixa")
                score -= 40

        diff = abs(float(current["ds18b201"]) - float(current["ds18b202"]))
        if diff > 20:
            reasons.append("sensores muito discrepantes")
            score -= 20

        if len(history) >= 4 and history["ds18b201"].std(ddof=0) < 0.001:
            reasons.append("sensor principal possivelmente travado")
            score -= 15

        score = float(max(0.0, min(100.0, score)))
        if score >= 85:
            status = "ok"
        elif score >= 60:
            status = "warning"
        else:
            status = "error"

        return {"status": status, "score": score, "reasons": reasons}

    def _stability_score(self, history: pd.DataFrame, erro_controle: float, taxa_variacao: float) -> float:
        """Consolida um score simples de estabilidade do processo."""
        temp_std = float(history["ds18b201"].std(ddof=0) or 0.0)
        variation_penalty = min(abs(taxa_variacao) * 500.0, 35.0)
        error_penalty = min(abs(erro_controle) * 8.0, 50.0)
        std_penalty = min(temp_std * 18.0, 35.0)
        score = 100.0 - (variation_penalty + error_penalty + std_penalty)
        return float(max(0.0, min(100.0, score)))

    def _overshoot_undershoot(self, history: pd.DataFrame, setpoint: float) -> tuple[float, float]:
        """Calcula overshoot e undershoot da temperatura principal em relação ao setpoint."""
        max_temp = float(history["ds18b201"].max())
        min_temp = float(history["ds18b201"].min())
        overshoot = max(0.0, max_temp - setpoint)
        undershoot = max(0.0, setpoint - min_temp)
        return float(overshoot), float(undershoot)

    def _cycle_time_with_contingency(self, history: pd.DataFrame) -> float | None:
        """Busca mais histórico progressivamente até conseguir medir um ciclo real."""
        cycle_time = self._cycle_time(history)
        if cycle_time is not None or history.empty:
            return cycle_time

        reference_timestamp = pd.Timestamp(history.iloc[-1]["timestamp"]).to_pydatetime()
        lookback_samples = max(self.CYCLE_TIME_INITIAL_LOOKBACK, len(history))
        previous_rows = len(history)

        while lookback_samples <= self.CYCLE_TIME_MAX_LOOKBACK:
            expanded_history = self._fetch_window(reference_timestamp, lookback_samples)
            cycle_time = self._cycle_time(expanded_history)
            if cycle_time is not None:
                return cycle_time

            if len(expanded_history) <= previous_rows or len(expanded_history) < lookback_samples:
                return None

            previous_rows = len(expanded_history)
            lookback_samples = ceil(lookback_samples * self.CYCLE_TIME_GROWTH_FACTOR)

        return None

    def _cycle_time(self, history: pd.DataFrame) -> float | None:
        """Calcula o ciclo médio do controle a partir de bordas de subida do MOSFET."""
        if len(history) < 4:
            return None
        mosfet = history["mosfet"].astype(int).to_numpy()
        timestamps = history["timestamp"].to_numpy()
        rising_edges = [
            pd.Timestamp(timestamps[idx])
            for idx in range(1, len(history))
            if mosfet[idx - 1] == 0 and mosfet[idx] == 1
        ]
        if len(rising_edges) < 2:
            return None
        periods = [
            self._duration_seconds(rising_edges[idx - 1], rising_edges[idx])
            for idx in range(1, len(rising_edges))
        ]
        if not periods:
            return None
        return float(np.median(periods))
