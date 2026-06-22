# API

Servicos FastAPI do projeto.

- `predict_service/`: API de predicao de temperatura na porta `8000`.
- `metrics_service/`: API de metricas do controlador na porta `8001`.
- `app/`: codigo compartilhado, schemas, configuracoes e servico do modelo.
- `data/`: artefatos do modelo e scalers usados pela predicao.

A API de predicao busca o historico diretamente no Firebase Realtime Database, entao nao depende mais de export local.

Para rodar a partir da raiz do projeto:

```bash
docker compose up --build
```

## Deploy no Render

No Render, configure o servico da API com:

- `Root Directory`: deixe vazio, usando a raiz do repositorio.
- `Dockerfile Path`: `api/Dockerfile`.

O Dockerfile foi preparado para build a partir da raiz do repositorio. Por isso ele copia `api/app`, `api/predict_service`, `api/metrics_service` e `api/data`.

Para subir a API de predicao, use:

- `Dockerfile Path`: `api/Dockerfile`.

Para subir a API de metricas como outro servico, use:

- `Dockerfile Path`: `api/Dockerfile.metrics`.

Como alternativa, tambem e possivel usar `api/Dockerfile` e sobrescrever o start command:

```bash
sh -c 'uvicorn metrics_service.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1'
```

## Predicao

Rotas:

- `GET /health`
- `POST /predict?horizon_steps=10`

O payload de entrada contem:

- `ds18b201`: temperatura principal do resistor.
- `ds18b202`: temperatura do ambiente.
- `mosfet`: estado do acionamento.
- `setpoint`: alvo atual do controle.
- `timestamp`: instante de referencia.

O `POST /predict` busca a janela historica anterior no Firebase, injeta o ponto atual recebido no body e retorna a temperatura prevista para o horizonte informado.

### Exemplo de consumo

```bash
curl -s -X POST 'http://localhost:8000/predict?horizon_steps=10' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
    "ds18b201": 35.19,
    "ds18b202": 25.19,
    "mosfet": 1,
    "setpoint": 34.6,
    "timestamp": "2026-06-01 16:33:01"
  }' | python3 -m json.tool
```

## Metricas

Rotas:

- `GET /health`
- `GET /metrics/summary`
- `GET /metrics/control`
- `GET /metrics/process`
- `GET /metrics/timing`
- `GET /metrics/duty-cycle`
- `GET /metrics/dashboard`

As metricas sao calculadas a partir dos registros do Firebase `digital_twin_dinamico_rev1`.

Resumo das principais chaves:

- `erro_controle`: `setpoint - ds18b201`.
- `diff_sensores`: `ds18b201 - ds18b202`.
- `taxa_variacao`: variacao da temperatura principal por segundo na janela.
- `tempo_mosfet_ligado`: soma do tempo em que o MOSFET ficou em `1`.
- `duty_cycle`: `tempo_mosfet_ligado / tempo_total * 100`.
- `cycle_time`: tempo medio entre duas viradas `0 -> 1` do MOSFET.
- `stability_score`: score operacional de 0 a 100.
- `sensor_health`: diagnostico simples dos sensores.

`cycle_time` tenta primeiro a janela informada. Se nao houver ciclos suficientes, a API expande a busca no Firebase a partir de 300 amostras e aumenta 40% a cada tentativa ate conseguir medir ou esgotar o historico disponivel.

### Exemplos de consumo

```bash
curl -s 'http://localhost:8001/metrics/summary?lookback_samples=20' | python3 -m json.tool
```

```bash
curl -s 'http://localhost:8001/metrics/duty-cycle?lookback_samples=20' | python3 -m json.tool
```

```bash
curl -s 'http://localhost:8001/metrics/dashboard?lookback_samples=20' | python3 -m json.tool
```
