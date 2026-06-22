from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PredictionRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ds18b201": 35.19,
                "ds18b202": 25.19,
                "mosfet": 1,
                "setpoint": 34.6,
                "timestamp": "2026-06-01 16:33:01",
            }
        }
    )

    ds18b201: float = Field(..., description="Temperatura medida pelo sensor ds18b201")
    ds18b202: float = Field(..., description="Temperatura medida pelo sensor ds18b202")
    mosfet: int = Field(..., ge=0, le=1, description="Estado do MOSFET")
    setpoint: float = Field(..., description="Temperatura de referência")
    timestamp: datetime = Field(..., description="Timestamp do ponto de referência")


class PredictionResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "predicted_temperature": 34.87,
                "reference_timestamp": "2026-06-01T16:33:01",
                "predicted_timestamp": "2026-06-01T16:35:31",
                "horizon_steps": 10,
                "window_size": 20,
            }
        }
    )

    predicted_temperature: float = Field(
        ..., description="Temperatura estimada pelo modelo para o horizonte futuro"
    )
    reference_timestamp: datetime = Field(
        ..., description="Timestamp informado na requisição de entrada"
    )
    predicted_timestamp: datetime = Field(
        ..., description="Timestamp estimado para a predição retornada"
    )
    horizon_steps: int = Field(..., description="Quantidade de passos à frente usados na estimativa")
    window_size: int = Field(..., description="Tamanho da janela temporal usada pelo modelo")


class EvaluationResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "predicted_temperature": 34.87,
                "actual_temperature": 34.72,
                "rmse": 0.15,
                "reference_timestamp": "2026-06-01T16:33:01",
                "predicted_timestamp": "2026-06-01T16:35:31",
                "horizon_steps": 10,
                "window_size": 20,
            }
        }
    )

    predicted_temperature: float = Field(
        ..., description="Temperatura estimada pelo modelo para o horizonte futuro"
    )
    actual_temperature: float = Field(
        ..., description="Temperatura real observada no dataset para o mesmo horizonte"
    )
    rmse: float = Field(
        ..., description="Erro quadrático médio entre a previsão e o valor real"
    )
    reference_timestamp: datetime = Field(
        ..., description="Timestamp informado na requisição de entrada"
    )
    predicted_timestamp: datetime = Field(
        ..., description="Timestamp estimado para a predição retornada"
    )
    horizon_steps: int = Field(..., description="Quantidade de passos à frente usados na estimativa")
    window_size: int = Field(..., description="Tamanho da janela temporal usada pelo modelo")
