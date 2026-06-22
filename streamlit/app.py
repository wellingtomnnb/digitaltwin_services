from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from math import isfinite
from urllib.error import URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st


FIREBASE_HOST = os.getenv("FIREBASE_HOST", "https://digitaltwim-default-rtdb.firebaseio.com").rstrip("/")
FIREBASE_COLLECTION = os.getenv("FIREBASE_COLLECTION", "digital_twin_dinamico_rev1").strip("/")
RUNTIME_CONFIG_PATH = os.getenv("RUNTIME_CONFIG_PATH", "digital_twin_runtime_config/prediction").strip("/")
METRICS_API_URL = os.getenv("METRICS_API_URL", "http://localhost:8001").rstrip("/")
DEFAULT_FETCH_LIMIT = int(os.getenv("FETCH_LIMIT", "300"))
LOCAL_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "America/Sao_Paulo"))
REFRESH_OPTIONS = {
    "5 segundos": 5,
    "15 segundos": 15,
    "30 segundos": 30,
    "1 minuto": 60,
}
PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}


st.set_page_config(
    page_title="Digital Twin",
    page_icon="DT",
    layout="wide",
)


def firebase_url(path: str) -> str:
    """Monta URLs REST do Firebase Realtime Database."""
    return f"{FIREBASE_HOST}/{path.strip('/')}.json"


def utc_now_iso() -> str:
    """Timestamp UTC usado para auditar alteracoes feitas pelo painel."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_float(value: object) -> float | None:
    """Converte valores numericos sem deixar NaN vazar para a interface."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def temp_text(value: object, decimals: int = 2) -> str:
    number = safe_float(value)
    return "n/d" if number is None else f"{number:.{decimals}f}°C"


def number_text(value: object, decimals: int = 2) -> str:
    number = safe_float(value)
    return "n/d" if number is None else f"{number:.{decimals}f}"


def percent_text(value: object) -> str:
    number = safe_float(value)
    return "n/d" if number is None else f"{number:.1f}%"


def duration_text(seconds: object) -> str:
    number = safe_float(seconds)
    if number is None:
        return "n/d"

    seconds_value = max(0, int(round(number)))
    if seconds_value < 60:
        return f"{seconds_value} s"

    minutes = int(round(seconds_value / 60))
    if minutes < 60:
        return f"{minutes} min"

    hours, remaining_minutes = divmod(minutes, 60)
    if remaining_minutes == 0:
        return f"{hours} h"
    return f"{hours} h {remaining_minutes} min"


def to_utc_aware(value: object) -> datetime | None:
    """Normaliza timestamps para UTC antes de calcular idades.

    Os registros do Arduino chegam sem informacao de fuso. Nesse caso,
    tratamos o horario como local do projeto para evitar diferencas artificiais.
    """
    if value is None or pd.isna(value):
        return None

    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None

    if ts.tzinfo is None:
        ts = ts.tz_localize(LOCAL_TIMEZONE)
    else:
        ts = ts.tz_convert(timezone.utc)
    return ts.tz_convert(timezone.utc).to_pydatetime()


def age_text(value: object) -> str:
    timestamp = to_utc_aware(value)
    if timestamp is None:
        return "n/d"
    return duration_text((datetime.now(timezone.utc) - timestamp).total_seconds())


def trend_info(frame: pd.DataFrame, column: str) -> tuple[str, str, float]:
    """Calcula tendencia recente com base nos ultimos pontos."""
    series = frame[column].dropna().tail(6)
    if len(series) < 2:
        return "→", "estável", 0.0

    delta = float(series.iloc[-1] - series.iloc[0])
    if delta > 0.08:
        return "▲", "subindo", delta
    if delta < -0.08:
        return "▼", "caindo", delta
    return "→", "estável", delta


def state_sentence(indicators: dict[str, object], latest: pd.Series, frame: pd.DataFrame) -> str:
    """Resume o estado atual em uma frase voltada para leitura humana."""
    resistor_icon, resistor_trend, resistor_delta = trend_info(frame, "ds18b201")
    control_error = safe_float(indicators.get("erro_controle"))
    setpoint = temp_text(latest["setpoint"])
    resistor = temp_text(latest["ds18b201"])
    mosfet_on = int(latest["mosfet"]) == 1

    if control_error is None:
        relation = "sem leitura suficiente para comparar com o alvo"
    elif abs(control_error) <= 0.5:
        relation = f"bem perto do alvo de {setpoint}"
    elif control_error < 0:
        relation = f"acima do alvo de {setpoint}"
    else:
        relation = f"abaixo do alvo de {setpoint}"

    actuator = "o aquecedor está ligado" if mosfet_on else "o aquecedor está desligado"
    delta_text = temp_text(abs(resistor_delta))
    return f"O resistor está em {resistor}, {relation}; a tendência recente está {resistor_icon} {resistor_trend} {delta_text}, e {actuator}."


@st.cache_data(ttl=1, show_spinner=False)
def fetch_latest_records(limit: int) -> pd.DataFrame:
    """Carrega os ultimos registros do Firebase e normaliza campos para graficos."""
    params = {
        "orderBy": '"$key"',
        "limitToLast": str(max(1, limit)),
    }
    url = f"{firebase_url(FIREBASE_COLLECTION)}?{urlencode(params, quote_via=quote)}"

    with urlopen(url, timeout=10) as response:
        raw = response.read().decode("utf-8")

    payload = json.loads(raw) if raw else None
    if not isinstance(payload, dict):
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    for firebase_key, value in sorted(payload.items()):
        if not isinstance(value, dict):
            continue

        prediction = value.get("prediction") if isinstance(value.get("prediction"), dict) else {}
        rows.append(
            {
                "firebase_key": firebase_key,
                "timestamp": value.get("timestamp"),
                "ds18b201": value.get("ds18b201"),
                "ds18b202": value.get("ds18b202"),
                "mosfet": value.get("mosfet"),
                "setpoint": value.get("setpoint"),
                "predicted_temperature": prediction.get("predicted_temperature"),
                "predicted_timestamp": prediction.get("predicted_timestamp"),
                "prediction_horizon_steps": prediction.get("horizon_steps"),
                "prediction_window_size": prediction.get("window_size"),
                "prediction_generated_at": prediction.get("generated_at"),
                "prediction_evaluated_at": prediction.get("evaluated_at"),
                "prediction_actual_temperature": prediction.get("actual_temperature"),
                "prediction_rmse": prediction.get("rmse"),
                "prediction_source": prediction.get("source"),
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame["predicted_timestamp"] = pd.to_datetime(frame["predicted_timestamp"], errors="coerce")
    frame["prediction_generated_at"] = pd.to_datetime(frame["prediction_generated_at"], errors="coerce")
    frame["prediction_evaluated_at"] = pd.to_datetime(frame["prediction_evaluated_at"], errors="coerce")

    for field in ("ds18b201", "ds18b202", "setpoint", "predicted_temperature", "prediction_actual_temperature", "prediction_rmse"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce")

    frame["mosfet"] = pd.to_numeric(frame["mosfet"], errors="coerce").fillna(0).astype(int)
    frame["prediction_horizon_steps"] = pd.to_numeric(frame["prediction_horizon_steps"], errors="coerce")
    frame["prediction_window_size"] = pd.to_numeric(frame["prediction_window_size"], errors="coerce")

    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return frame


@st.cache_data(ttl=1, show_spinner=False)
def fetch_runtime_config() -> dict[str, object]:
    """Le a configuracao dinamica usada pelo trigger."""
    try:
        with urlopen(firebase_url(RUNTIME_CONFIG_PATH), timeout=10) as response:
            raw = response.read().decode("utf-8")
    except URLError:
        return {}

    payload = json.loads(raw) if raw else None
    return payload if isinstance(payload, dict) else {}


def update_runtime_config(horizon_steps: int) -> None:
    """Grava no Firebase o horizonte que o trigger deve usar em novas previsoes."""
    payload = {
        "horizon_steps": int(horizon_steps),
        "updated_at": utc_now_iso(),
        "updated_by": "streamlit",
    }
    request = Request(
        firebase_url(RUNTIME_CONFIG_PATH),
        data=json.dumps(payload).encode("utf-8"),
        method="PATCH",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=10) as response:
        response.read()
    fetch_runtime_config.clear()


@st.cache_data(ttl=1, show_spinner=False)
def fetch_metrics_dashboard(lookback_samples: int) -> dict[str, object] | None:
    """Tenta usar a API de metricas para os indicadores derivados."""
    url = f"{METRICS_API_URL}/metrics/dashboard?{urlencode({'lookback_samples': lookback_samples})}"
    try:
        with urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def local_indicators(frame: pd.DataFrame) -> dict[str, object]:
    """Resumo minimo para quando a API de metricas nao responder."""
    latest = frame.iloc[-1]
    elapsed = frame["timestamp"].diff().dt.total_seconds().fillna(0)
    total_seconds = float(elapsed.sum())
    mosfet_seconds = float((elapsed * frame["mosfet"]).sum())
    duty_cycle = (mosfet_seconds / total_seconds * 100) if total_seconds > 0 else 0.0

    return {
        "erro_controle": float(latest["setpoint"] - latest["ds18b201"]),
        "diff_sensores": float(latest["ds18b201"] - latest["ds18b202"]),
        "duty_cycle": duty_cycle,
        "tempo_mosfet_ligado": mosfet_seconds,
    }


def indicators_from_payload(payload: dict[str, object] | None, frame: pd.DataFrame) -> dict[str, object]:
    if isinstance(payload, dict) and isinstance(payload.get("indicadores"), dict):
        return payload["indicadores"]
    return local_indicators(frame)


def horizon_change_points(frame: pd.DataFrame) -> pd.DataFrame:
    """Identifica pontos em que o horizonte salvo pela trigger mudou."""
    valid = frame.dropna(subset=["prediction_horizon_steps"]).copy()
    if valid.empty:
        return valid

    changed = valid["prediction_horizon_steps"].ne(valid["prediction_horizon_steps"].shift())
    return valid[changed]


def control_state_label(value: object) -> str:
    labels = {
        "acima_do_setpoint": "acima do alvo",
        "abaixo_do_setpoint": "abaixo do alvo",
        "dentro_da_faixa": "dentro da faixa",
        "estavel": "estável",
    }
    return labels.get(str(value), str(value) if value is not None else "n/d")


def sensor_health_text(value: object) -> str:
    if not isinstance(value, dict):
        return "n/d"
    status = str(value.get("status", "n/d"))
    score = safe_float(value.get("score"))
    if score is None:
        return status
    return f"{status} ({score:.0f}/100)"


def score_text(value: object) -> str:
    """Formata scores de 0 a 100 sem parecer unidade física."""
    score = safe_float(value)
    return "n/d" if score is None else f"{score:.0f}/100"


def stability_label(value: object) -> str:
    """Traduz o score de estabilidade para uma leitura humana."""
    score = safe_float(value)
    if score is None:
        return "sem leitura"
    if score >= 85:
        return "estável"
    if score >= 65:
        return "boa"
    if score >= 45:
        return "oscilando"
    return "instável"


def control_gap_label(error_value: object) -> tuple[str, str | None]:
    """Descreve a distancia entre temperatura do resistor e setpoint."""
    error = safe_float(error_value)
    if error is None:
        return "sem leitura", None
    if abs(error) <= 0.5:
        return "no alvo", f"{abs(error):.2f}°C"
    if error < 0:
        return "acima do alvo", f"{abs(error):.2f}°C"
    return "abaixo do alvo", f"{abs(error):.2f}°C"


def mosfet_state_text(is_on: bool) -> str:
    return "ligado" if is_on else "desligado"


def rmse_text(value: object) -> str:
    """Formata o RMSE como erro em temperatura."""
    return temp_text(value)


def friendly_metric_rows(indicators: dict[str, object]) -> list[dict[str, str]]:
    """Traduz indicadores tecnicos em perguntas simples."""
    return [
        {
            "Pergunta": "O resistor está perto do alvo?",
            "Resposta": temp_text(indicators.get("erro_controle")),
            "Leitura": "valor positivo indica que falta aquecer; negativo indica que passou do alvo",
        },
        {
            "Pergunta": "Quanto o resistor difere do ambiente?",
            "Resposta": temp_text(indicators.get("diff_sensores")),
            "Leitura": "mostra o aquecimento real acima da temperatura ambiente",
        },
        {
            "Pergunta": "Por quanto tempo o aquecedor ficou ligado?",
            "Resposta": duration_text(indicators.get("tempo_mosfet_ligado")),
            "Leitura": "tempo acumulado de acionamento na janela selecionada",
        },
        {
            "Pergunta": "Qual foi a intensidade de uso?",
            "Resposta": percent_text(indicators.get("duty_cycle")),
            "Leitura": "percentual da janela em que o MOSFET ficou ligado",
        },
        {
            "Pergunta": "O comportamento está estável?",
            "Resposta": number_text(indicators.get("stability_score"), 1),
            "Leitura": "quanto mais perto de 100, mais estável está a resposta",
        },
        {
            "Pergunta": "O controle está em que estado?",
            "Resposta": control_state_label(indicators.get("estado_controle")),
            "Leitura": "interpretação atual da relação entre temperatura e setpoint",
        },
        {
            "Pergunta": "Os sensores parecem confiáveis?",
            "Resposta": sensor_health_text(indicators.get("sensor_health")),
            "Leitura": "checagem simples de leituras inválidas e consistência",
        },
        {
            "Pergunta": "Houve excesso acima do alvo?",
            "Resposta": temp_text(indicators.get("overshoot")),
            "Leitura": "quanto a temperatura passou do setpoint na janela",
        },
        {
            "Pergunta": "Houve falta abaixo do alvo?",
            "Resposta": temp_text(indicators.get("undershoot")),
            "Leitura": "quanto a temperatura ficou abaixo do setpoint na janela",
        },
        {
            "Pergunta": "Quanto dura um ciclo de acionamento?",
            "Resposta": duration_text(indicators.get("cycle_time")),
            "Leitura": "tempo típico entre novos acionamentos do MOSFET",
        },
    ]


def temperature_chart(frame: pd.DataFrame) -> go.Figure:
    """Grafico principal de temperaturas, setpoint e previsoes gravadas."""
    resistor_icon, _, _ = trend_info(frame, "ds18b201")
    ambient_icon, _, _ = trend_info(frame, "ds18b202")
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.72, 0.28],
    )

    fig.add_trace(
        go.Scatter(
            x=frame["timestamp"],
            y=frame["ds18b201"],
            name=f"resistor {resistor_icon}",
            mode="lines",
            line={"width": 3.2, "color": "#276749"},
            hovertemplate="Resistor: %{y:.2f}°C<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=frame["timestamp"],
            y=frame["ds18b202"],
            name=f"ambiente {ambient_icon}",
            mode="lines",
            line={"width": 2.2, "color": "#3b82f6"},
            hovertemplate="Ambiente: %{y:.2f}°C<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=frame["timestamp"],
            y=frame["setpoint"],
            name="alvo",
            mode="lines",
            line={"width": 2.1, "color": "#8b6f47", "dash": "dot"},
            hovertemplate="Alvo: %{y:.2f}°C<extra></extra>",
        )
    )

    predicted = frame.dropna(subset=["predicted_temperature"])
    if not predicted.empty:
        fig.add_trace(
            go.Scatter(
                x=predicted["timestamp"],
                y=predicted["predicted_temperature"],
                name="previsão",
                mode="lines+markers",
                line={"color": "#ef8f8f", "dash": "dash", "width": 2.2},
                marker={"size": 4},
            hovertemplate="Previsão: %{y:.2f}°C<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=frame["timestamp"],
            y=frame["mosfet"].fillna(0).astype(int),
            name="mosfet",
            mode="lines",
            line={"width": 2.2, "color": "#276749", "shape": "hv"},
            hovertemplate="MOSFET: %{y}<extra></extra>",
        ),
        row=2,
        col=1,
    )
    fig.add_hline(y=0.5, line_width=1, line_dash="dot", line_color="#cbd5c0", row=2, col=1)

    latest = frame.iloc[-1]
    fig.add_annotation(
        x=latest["timestamp"],
        y=latest["ds18b201"],
        text=f"agora {temp_text(latest['ds18b201'])}",
        showarrow=True,
        arrowhead=2,
        ax=32,
        ay=-28,
        bgcolor="rgba(255,255,255,0.9)",
        bordercolor="#cbd5c0",
        font={"size": 11, "color": "#1f3b2d"},
    )

    for _, row in horizon_change_points(frame).iterrows():
        timestamp = row["timestamp"].isoformat()
        fig.add_shape(
            type="line",
            x0=timestamp,
            x1=timestamp,
            y0=0,
            y1=1,
            xref="x",
            yref="paper",
            line={"color": "#c47a20", "dash": "dot", "width": 1},
        )
        fig.add_annotation(
            x=timestamp,
            y=0.01,
            xref="x",
            yref="paper",
            text=f"h={int(row['prediction_horizon_steps'])}",
            showarrow=False,
            yanchor="bottom",
            textangle=-90,
            font={"color": "#8a4a03", "size": 10},
            bgcolor="rgba(255, 246, 225, 0.92)",
            bordercolor="#e7bd82",
            borderpad=2,
        )

    fig.update_yaxes(title_text="Temperatura (°C)", row=1, col=1)
    fig.update_yaxes(
        title_text="MOSFET",
        row=2,
        col=1,
        tickmode="array",
        tickvals=[0, 1],
        ticktext=["desligado", "ligado"],
        range=[-0.1, 1.1],
    )
    fig.update_xaxes(title_text=None, row=1, col=1)
    fig.update_xaxes(title_text=None, row=2, col=1)
    fig.update_layout(
        height=520,
        margin={"l": 16, "r": 16, "t": 54, "b": 36},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.03,
            "xanchor": "left",
            "x": 0,
            "font": {"size": 12},
        },
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def mosfet_chart(frame: pd.DataFrame) -> go.Figure:
    """Grafico visual de liga/desliga do MOSFET."""
    colors = frame["mosfet"].map({1: "#276749", 0: "#d5ddd2"})
    fig = go.Figure(
        go.Bar(
            x=frame["timestamp"],
            y=[1] * len(frame),
            marker={"color": colors},
            hovertemplate="MOSFET: %{customdata}<extra></extra>",
            customdata=frame["mosfet"].map({1: "ligado", 0: "desligado"}),
            name="MOSFET",
        )
    )
    fig.update_layout(
        height=160,
        margin={"l": 16, "r": 16, "t": 18, "b": 24},
        showlegend=False,
        yaxis={"visible": False},
        xaxis_title=None,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        bargap=0,
    )
    return fig


def temp_range(frame: pd.DataFrame) -> tuple[float, float]:
    """Define uma escala comum para os visuais de temperatura."""
    series: list[pd.Series] = []
    for column in ("ds18b201", "ds18b202", "setpoint", "predicted_temperature"):
        if column not in frame:
            continue
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        if not values.empty:
            series.append(values)

    if not series:
        return 0.0, 50.0

    values = pd.concat(series, ignore_index=True)
    if values.empty:
        return 0.0, 50.0

    low = float(values.min()) - 1.5
    high = float(values.max()) + 1.5
    if high - low < 6:
        center = (high + low) / 2
        return center - 3, center + 3
    return low, high


def temperature_gauge(
    title: str,
    value: object,
    *,
    bounds: tuple[float, float],
    color: str,
    threshold: object | None = None,
    delta_reference: object | None = None,
) -> go.Figure:
    """Gauge compacto para contar a história térmica sem texto longo."""
    numeric_value = safe_float(value) or 0.0
    gauge: dict[str, object] = {
        "axis": {"range": list(bounds), "tickfont": {"size": 10}},
        "bar": {"color": color, "thickness": 0.32},
        "bgcolor": "rgba(255,255,255,0)",
        "borderwidth": 0,
        "steps": [
            {"range": [bounds[0], bounds[0] + (bounds[1] - bounds[0]) * 0.33], "color": "#eef4ff"},
            {"range": [bounds[0] + (bounds[1] - bounds[0]) * 0.33, bounds[0] + (bounds[1] - bounds[0]) * 0.66], "color": "#f7faf4"},
            {"range": [bounds[0] + (bounds[1] - bounds[0]) * 0.66, bounds[1]], "color": "#fff4e6"},
        ],
    }

    threshold_value = safe_float(threshold)
    if threshold_value is not None:
        gauge["threshold"] = {
            "line": {"color": "#8b6f47", "width": 3},
            "thickness": 0.75,
            "value": threshold_value,
        }

    indicator: dict[str, object] = {
        "mode": "gauge+number",
        "value": numeric_value,
        "number": {"suffix": "°C", "font": {"size": 24}},
        "title": {"text": title, "font": {"size": 13}},
        "gauge": gauge,
    }

    reference = safe_float(delta_reference)
    if reference is not None:
        indicator["mode"] = "gauge+number+delta"
        indicator["delta"] = {"reference": reference, "suffix": "°C", "font": {"size": 12}}

    fig = go.Figure(go.Indicator(**indicator))
    fig.update_layout(
        height=188,
        margin={"l": 12, "r": 12, "t": 36, "b": 12},
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def duty_cycle_figure(duty_cycle: object) -> go.Figure:
    """Destaque visual para a razao ciclica do aquecedor."""
    duty = min(100.0, max(0.0, safe_float(duty_cycle) or 0.0))
    active_color = "#276749" if duty >= 50 else "#c47a20"
    fig = go.Figure(
        go.Pie(
            values=[duty, max(0.0, 100.0 - duty)],
            hole=0.72,
            sort=False,
            direction="clockwise",
            marker={"colors": [active_color, "#e8eee6"], "line": {"color": "#ffffff", "width": 2}},
            textinfo="none",
            hovertemplate="%{value:.1f}%<extra></extra>",
        )
    )
    fig.add_annotation(
        text=percent_text(duty),
        x=0.5,
        y=0.48,
        showarrow=False,
        font={"size": 24, "color": "#101813"},
    )
    fig.add_annotation(
        text="razão cíclica",
        x=0.5,
        y=0.28,
        showarrow=False,
        font={"size": 12, "color": "#425040"},
    )
    fig.update_layout(
        height=210,
        margin={"l": 8, "r": 8, "t": 24, "b": 8},
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def mosfet_icon_figure(is_on: bool) -> go.Figure:
    """Mostra apenas o estado ligado/desligado do MOSFET por simbolo."""
    active_color = "#276749" if is_on else "#9aa69a"
    fig = go.Figure()
    fig.add_shape(
        type="circle",
        x0=0.2,
        y0=0.2,
        x1=0.8,
        y1=0.8,
        line={"color": active_color, "width": 2},
        fillcolor="rgba(255,255,255,0)",
    )
    fig.add_annotation(
        text="⏻" if is_on else "○",
        x=0.5,
        y=0.5,
        showarrow=False,
        font={"size": 54, "color": active_color},
    )
    fig.update_layout(
        height=210,
        margin={"l": 8, "r": 8, "t": 24, "b": 8},
        showlegend=False,
        title={"text": "", "font": {"size": 1}},
        xaxis={"visible": False, "range": [0, 1]},
        yaxis={"visible": False, "range": [0, 1], "scaleanchor": "x"},
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def status_panel_figure(
    rmse_value: object,
    stability_score: object,
    sensor_score: object | None,
    sensor_status: str,
) -> go.Figure:
    """Agrupa RMSE, estabilidade e saude dos sensores em um unico painel."""
    rmse = safe_float(rmse_value)
    stability = min(100.0, max(0.0, safe_float(stability_score) or 0.0))
    sensors = min(100.0, max(0.0, safe_float(sensor_score) or 0.0))

    fig = make_subplots(
        rows=1,
        cols=3,
        specs=[[{"type": "indicator"}, {"type": "indicator"}, {"type": "indicator"}]],
        column_widths=[0.33, 0.33, 0.34],
        horizontal_spacing=0.08,
    )

    fig.add_trace(
        go.Indicator(
            mode="number" if rmse is None else "number+delta",
            value=0.0 if rmse is None else rmse,
            number={"suffix": "°C", "font": {"size": 26}},
            title={"text": "RMSE", "font": {"size": 14}},
            delta=None if rmse is None else {"reference": 0.0, "suffix": "°C", "font": {"size": 12}},
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Indicator(
            mode="gauge+number",
            value=stability,
            number={"suffix": "/100", "font": {"size": 26}},
            title={"text": "estabilidade", "font": {"size": 14}},
            gauge={
                "shape": "bullet",
                "axis": {"range": [0, 100], "tickfont": {"size": 10}},
                "bar": {"color": "#276749"},
                "steps": [
                    {"range": [0, 45], "color": "#f7ece8"},
                    {"range": [45, 65], "color": "#fff4db"},
                    {"range": [65, 85], "color": "#edf7ed"},
                    {"range": [85, 100], "color": "#d8f1de"},
                ],
                "threshold": {"line": {"color": "#101813", "width": 2}, "value": 80},
            },
        ),
        row=1,
        col=2,
    )

    fig.add_trace(
        go.Indicator(
            mode="gauge+number",
            value=sensors,
            number={"suffix": "/100", "font": {"size": 26}},
            title={"text": "sensores", "font": {"size": 14}},
            gauge={
                "shape": "bullet",
                "axis": {"range": [0, 100], "tickfont": {"size": 10}},
                "bar": {"color": "#3b82f6"},
                "steps": [
                    {"range": [0, 50], "color": "#f7f7fb"},
                    {"range": [50, 75], "color": "#eef4ff"},
                    {"range": [75, 100], "color": "#dcebff"},
                ],
                "threshold": {"line": {"color": "#101813", "width": 2}, "value": 85},
            },
        ),
        row=1,
        col=3,
    )

    fig.add_annotation(
        x=0.16,
        y=0.07,
        xref="paper",
        yref="paper",
        text="erro da previsão",
        showarrow=False,
        font={"size": 11, "color": "#64748b"},
    )
    fig.add_annotation(
        x=0.50,
        y=0.07,
        xref="paper",
        yref="paper",
        text="quanto mais alto, mais estável",
        showarrow=False,
        font={"size": 11, "color": "#64748b"},
    )
    fig.add_annotation(
        x=0.84,
        y=0.07,
        xref="paper",
        yref="paper",
        text=sensor_status,
        showarrow=False,
        font={"size": 11, "color": "#64748b"},
    )

    fig.update_layout(
        height=250,
        margin={"l": 12, "r": 12, "t": 32, "b": 18},
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


def compact_metric(label: str, value: str, delta: str | None = None) -> None:
    """Métrica nativa compacta para evitar HTML customizado no corpo do painel."""
    st.metric(label, value, delta)


def neutral_metric(label: str, value: str, detail: str | None = None) -> None:
    """Métrica para estado/pontuação, sem seta de variação."""
    st.metric(label, value, detail, delta_color="off")


def metrics_api_chart(payload: dict[str, object] | None, key: str) -> go.Figure | None:
    """Converte os graficos retornados pela API de metricas em uma figura Plotly."""
    if not isinstance(payload, dict):
        return None

    chart = payload.get("graficos")
    if not isinstance(chart, dict):
        return None

    section = chart.get(key)
    if not isinstance(section, dict):
        return None

    timestamps = pd.to_datetime(section.get("timestamp", []), errors="coerce")
    title = str(section.get("titulo", key))
    fig = go.Figure()

    if key == "atuacao":
        fig.add_trace(
            go.Bar(
                x=timestamps,
                y=pd.to_numeric(section.get("mosfet", []), errors="coerce"),
                name="MOSFET",
                marker={"color": "#276749"},
                hovertemplate="MOSFET: %{y}<extra></extra>",
            )
        )
        fig.update_layout(
            yaxis_title="Estado",
            yaxis={"tickmode": "array", "tickvals": [0, 1], "ticktext": ["desligado", "ligado"]},
            xaxis_title=None,
            height=210,
            margin={"l": 16, "r": 16, "t": 44, "b": 24},
            showlegend=False,
        )
    elif key == "controle":
        fig.add_trace(
            go.Scatter(
                x=timestamps,
                y=pd.to_numeric(section.get("erro_controle", []), errors="coerce"),
                name="erro de controle",
                mode="lines",
                line={"width": 2.5, "color": "#c47a20"},
                hovertemplate="Erro: %{y:.2f}°C<extra></extra>",
            )
        )
        fig.add_hline(y=0, line_width=1, line_dash="dot", line_color="#425040")
        fig.update_layout(
            yaxis_title="Erro (°C)",
            xaxis_title=None,
            height=210,
            margin={"l": 16, "r": 16, "t": 44, "b": 24},
            showlegend=False,
        )
    else:
        return None

    fig.update_layout(
        title={"text": title, "x": 0.02, "font": {"size": 14}},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


st.markdown(
    """
    <style>
      .block-container {
        padding-top: 1.25rem;
        padding-bottom: 2rem;
        max-width: 1500px;
      }
      [data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #dce6d7;
        border-radius: 8px;
        padding: 0.85rem 0.9rem;
        min-height: 104px;
        box-shadow: 0 8px 22px rgba(20, 31, 20, 0.045);
        overflow: hidden;
      }
      [data-testid="stMetricLabel"] {
        color: #425040;
        font-weight: 650;
      }
      [data-testid="stMetricLabel"] p {
        white-space: normal;
        overflow-wrap: anywhere;
      }
      [data-testid="stMetricValue"] {
        color: #101813;
        font-weight: 760;
      }
      [data-testid="stMetricValue"] div {
        font-size: clamp(1.25rem, 2.4vw, 2rem);
        white-space: normal;
        overflow-wrap: anywhere;
      }
      [data-testid="stMetricDelta"] {
        font-size: 0.84rem;
      }
      [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: #dce6d7;
        border-radius: 10px;
        box-shadow: 0 8px 22px rgba(20, 31, 20, 0.04);
        overflow: hidden;
      }
      .stPlotlyChart {
        overflow: hidden;
      }
      @media (max-width: 900px) {
        [data-testid="stHorizontalBlock"] {
          flex-wrap: wrap;
          gap: 0.75rem;
        }
        [data-testid="column"] {
          flex: 1 1 100% !important;
          min-width: min(100%, 280px) !important;
          width: 100% !important;
        }
      }
    </style>
    """,
    unsafe_allow_html=True,
)


config = fetch_runtime_config()

with st.sidebar:
    st.header("Controle")
    fetch_limit = st.slider("Registros carregados", 50, 1000, DEFAULT_FETCH_LIMIT, 50)
    lookback_samples = st.slider("Janela analisada", 20, 500, 200, 10)
    refresh_label = st.selectbox("Atualizar painel a cada", list(REFRESH_OPTIONS), index=0)
    refresh_seconds = REFRESH_OPTIONS[refresh_label]
    if st.button("Atualizar agora", use_container_width=True):
        fetch_latest_records.clear()
        fetch_metrics_dashboard.clear()
        fetch_runtime_config.clear()
        st.rerun()

    st.divider()
    st.subheader("Próximas previsões")
    current_horizon = int(config.get("horizon_steps") or 10)
    selected_horizon = st.number_input("horizon_steps", min_value=1, max_value=120, value=current_horizon)
    if st.button("Aplicar para novos registros", type="primary", use_container_width=True):
        update_runtime_config(int(selected_horizon))
        st.success("Configuração salva. O trigger aplicará nos próximos registros.")
        st.rerun()

    updated_at = config.get("updated_at", "n/d")
    st.caption(f"Config atual: horizon_steps={current_horizon} | atualizado em {updated_at}")

st.title("Digital Twin")
st.caption("Leitura em tempo quase real do comportamento térmico e das previsões gravadas pelo trigger.")


@st.fragment(run_every=refresh_seconds)
def render_dashboard(fetch_limit: int, lookback_samples: int, refresh_seconds: int) -> None:
    """Atualiza somente a area principal do painel no intervalo escolhido."""
    try:
        data = fetch_latest_records(fetch_limit)
    except Exception as exc:
        st.error(f"Não foi possível carregar o Firebase: {exc}")
        return

    if data.empty:
        st.warning("Nenhum registro encontrado no Firebase.")
        return

    visible = data.tail(lookback_samples).reset_index(drop=True)
    latest = visible.iloc[-1]
    prediction_history = data.dropna(subset=["predicted_temperature"]).copy()
    latest_prediction = None if prediction_history.empty else prediction_history.iloc[-1]
    evaluated_prediction_history = data.dropna(subset=["prediction_rmse"]).copy()
    latest_evaluated_prediction = None if evaluated_prediction_history.empty else evaluated_prediction_history.iloc[-1]
    previous_evaluated_prediction = (
        None if len(evaluated_prediction_history) < 2 else evaluated_prediction_history.iloc[-2]
    )
    metrics_payload = fetch_metrics_dashboard(min(lookback_samples, 500))
    indicators = indicators_from_payload(metrics_payload, visible)
    resistor_icon, resistor_trend, resistor_delta = trend_info(visible, "ds18b201")
    ambient_icon, ambient_trend, ambient_delta = trend_info(visible, "ds18b202")
    latest_timestamp = to_utc_aware(latest["timestamp"])
    now_utc = datetime.now(timezone.utc)
    last_point_age = duration_text((now_utc - latest_timestamp).total_seconds()) if latest_timestamp else "n/d"
    has_prediction = latest_prediction is not None
    has_evaluated_prediction = latest_evaluated_prediction is not None
    prediction_source = latest_evaluated_prediction if has_evaluated_prediction else latest_prediction
    prediction_generated_at = to_utc_aware(prediction_source["prediction_generated_at"]) if prediction_source is not None else None
    prediction_record_timestamp = to_utc_aware(prediction_source["timestamp"]) if prediction_source is not None else None
    prediction_age_reference = prediction_generated_at or prediction_record_timestamp
    prediction_age = (
        duration_text((now_utc - prediction_age_reference).total_seconds()) if prediction_age_reference else None
    )
    mosfet_on = int(latest["mosfet"]) == 1
    prediction_rmse = latest_evaluated_prediction["prediction_rmse"] if has_evaluated_prediction else None
    previous_rmse = (
        previous_evaluated_prediction["prediction_rmse"] if previous_evaluated_prediction is not None else None
    )
    rmse_delta = (
        safe_float(prediction_rmse) - safe_float(previous_rmse)
        if prediction_rmse is not None and previous_rmse is not None
        else None
    )
    bounds_source = (
        pd.concat([visible, prediction_source.to_frame().T], ignore_index=True)
        if prediction_source is not None
        else visible
    )
    bounds = temp_range(bounds_source)
    control_error = indicators.get("erro_controle")
    control_label, control_delta = control_gap_label(control_error)
    duty_cycle = indicators.get("duty_cycle")
    stability_score = indicators.get("stability_score")

    sensor_health = indicators.get("sensor_health")
    sensor_status = sensor_health_text(sensor_health)
    sensor_score = None
    if isinstance(sensor_health, dict):
        sensor_status = str(sensor_health.get("status", "n/d"))
        sensor_score = safe_float(sensor_health.get("score"))

    st.caption(f"Atualiza a cada {duration_text(refresh_seconds)} · última leitura há {last_point_age}")

    st.subheader("Leituras atuais")
    first_row = st.columns(3)
    with first_row[0]:
        with st.container(border=True):
            st.plotly_chart(
                temperature_gauge(
                    "ambiente",
                    latest["ds18b202"],
                    bounds=bounds,
                    color="#3b82f6",
                ),
                use_container_width=True,
                config=PLOTLY_CONFIG,
                key="ambient_gauge",
            )
            compact_metric("tendência", f"{ambient_icon} {ambient_trend}", f"{ambient_delta:+.2f}°C")

    with first_row[1]:
        with st.container(border=True):
            st.plotly_chart(
                temperature_gauge(
                    "resistor",
                    latest["ds18b201"],
                    bounds=bounds,
                    color="#276749",
                    threshold=latest["setpoint"],
                    delta_reference=latest["setpoint"],
                ),
                use_container_width=True,
                config=PLOTLY_CONFIG,
                key="resistor_gauge",
            )
            compact_metric("tendência", f"{resistor_icon} {resistor_trend}", f"{resistor_delta:+.2f}°C")

    with first_row[2]:
        with st.container(border=True):
            st.plotly_chart(
                duty_cycle_figure(duty_cycle),
                use_container_width=True,
                config=PLOTLY_CONFIG,
                key="duty_cycle_figure",
            )
            with st.container(border=True):
                st.markdown("**MOSFET**")
                st.markdown(f"**{mosfet_state_text(mosfet_on)}**")
                # st.caption(f"tempo ligado: {duration_text(indicators.get('tempo_mosfet_ligado'))}")

    second_row = st.columns(3)
    with second_row[0]:
        with st.container(border=True):
            st.metric(
                "alvo",
                temp_text(latest["setpoint"]),
                f"{control_label} · {control_delta}" if control_delta else control_label,
            )
            st.caption(f"temperatura atual do resistor: {temp_text(latest['ds18b201'])}")

    with second_row[1]:
        with st.container(border=True):
            st.metric("estabilidade", stability_label(stability_score), score_text(stability_score))
            st.caption(f"ciclo típico: {duration_text(indicators.get('cycle_time'))}")

    with second_row[2]:
        with st.container(border=True):
            st.metric(
                "RMSE",
                rmse_text(prediction_rmse),
                None if rmse_delta is None else f"{rmse_delta:+.2f}°C",
                delta_color="inverse",
            )
            st.caption(f"Diferença entre setpoint e sensor: {temp_text(control_error)}")

    st.subheader("Linha do tempo")
    st.plotly_chart(temperature_chart(visible), use_container_width=True, config=PLOTLY_CONFIG)

    changes = horizon_change_points(visible)
    if not changes.empty:
        with st.expander("Mudanças no horizonte de previsão"):
            st.dataframe(
                pd.DataFrame(
                    {
                        "quando": changes["timestamp"].dt.strftime("%d/%m %H:%M"),
                        "horizon_steps usado": changes["prediction_horizon_steps"].astype(int).astype(str),
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

    with st.expander("Leituras traduzidas"):
        st.dataframe(pd.DataFrame(friendly_metric_rows(indicators)).astype(str), use_container_width=True, hide_index=True)

    with st.expander("Dados recentes"):
        recent = visible[
            [
                "timestamp",
                "ds18b201",
                "ds18b202",
                "setpoint",
                "mosfet",
                "predicted_temperature",
                "prediction_horizon_steps",
                "prediction_generated_at",
            ]
        ].copy()
        recent["timestamp"] = recent["timestamp"].dt.strftime("%d/%m %H:%M:%S")
        recent["ds18b201"] = recent["ds18b201"].map(temp_text)
        recent["ds18b202"] = recent["ds18b202"].map(temp_text)
        recent["setpoint"] = recent["setpoint"].map(temp_text)
        recent["mosfet"] = recent["mosfet"].map({1: "ligado", 0: "desligado"})
        recent["predicted_temperature"] = recent["predicted_temperature"].map(temp_text)
        recent["prediction_horizon_steps"] = recent["prediction_horizon_steps"].fillna("n/d").astype(str)
        recent["prediction_generated_at"] = recent["prediction_generated_at"].dt.strftime("%d/%m %H:%M:%S").fillna("n/d")
        recent = recent.rename(
            columns={
                "timestamp": "quando",
                "ds18b201": "resistor",
                "ds18b202": "ambiente",
                "setpoint": "alvo",
                "mosfet": "aquecedor",
                "predicted_temperature": "previsão",
                "prediction_horizon_steps": "horizon_steps",
                "prediction_generated_at": "previsão gerada em",
            }
        )
        st.dataframe(recent.astype(str), use_container_width=True, hide_index=True)


render_dashboard(fetch_limit, lookback_samples, refresh_seconds)
