# Digital Twin

Monorepo do sistema de controle e acompanhamento térmico.

## Visao Geral

- `arduino/`: firmware do ESP32 que coleta sensores e envia dados ao Firebase.
- `api/`: API FastAPI para predicao e metricas.
- `webhook/`: espaco para integracoes por evento.
- `streamlit/`: painel de relatorios.

## Execucao

```bash
docker compose up --build
```

## Servicos

- API de predicao: `http://localhost:8000`
- API de metricas: `http://localhost:8001`

## Documentacao

- [Arduino](arduino/README.md)
- [API](api/README.md)
- [Webhook](webhook/README.md)
- [Streamlit](streamlit/README.md)
