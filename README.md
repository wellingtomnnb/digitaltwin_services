# Digital Twin

Monorepo do sistema de controle e acompanhamento térmico.

## Visao Geral

- `arduino/`: firmware do ESP32 que coleta sensores e envia dados ao Firebase.
- `api/`: API FastAPI para predicao e metricas.
- `trigger/`: processo interno que atualiza registros do Firebase com previsoes.
- `streamlit/`: painel de relatorios.

## Execucao

```bash
docker compose up --build
```

## Servicos

- API de predicao: `http://localhost:8000`
- API de metricas: `http://localhost:8001`
- Trigger: container interno sem porta publica.

## Documentacao

- [Arduino](arduino/README.md)
- [API](api/README.md)
- [Trigger](trigger/README.md)
- [Streamlit](streamlit/README.md)
