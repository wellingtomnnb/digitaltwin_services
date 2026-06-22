# Trigger

Servico interno responsavel por enriquecer novos registros do Firebase com a previsao do modelo.

Ele roda em loop dentro de um container, busca os registros mais recentes no Realtime Database, chama `POST /predict` no container `predictor` e grava a resposta no proprio registro, dentro da chave `prediction`.

## Fluxo

1. ESP32 grava o registro bruto no Firebase.
2. `trigger` identifica registros recentes sem `prediction`.
3. `trigger` envia o payload para `http://predictor:8000/predict`.
4. `trigger` atualiza o mesmo registro no Firebase com a previsao.
5. Streamlit pode ler o historico ja enriquecido direto do Firebase.

## Variaveis

- `FIREBASE_HOST`: URL do Realtime Database.
- `FIREBASE_COLLECTION`: colecao monitorada. Padrao: `digital_twin_dinamico_rev1`.
- `PREDICTOR_URL`: URL interna do servico de predicao. Padrao: `http://predictor:8000/predict`.
- `HORIZON_STEPS`: horizonte usado para novas previsoes. Padrao: `10`.
- `POLL_INTERVAL_SECONDS`: intervalo entre buscas no Firebase. Padrao: `2`.
- `FETCH_LIMIT`: quantidade de registros recentes lidos por ciclo. Padrao: `30`.
- `PREDICTION_FIELD`: chave gravada no registro. Padrao: `prediction`.

Quando `HORIZON_STEPS` mudar, apenas os novos registros sem `prediction` passam a ser salvos com o novo valor. Isso permite destacar no grafico onde a configuracao mudou.

## Deploy no Render

Configure como Background Worker:

- `Root Directory`: deixe vazio, usando a raiz do repositorio.
- `Dockerfile Path`: `trigger/Dockerfile`.
- `PREDICTOR_URL`: URL publica ou privada do servico de predicao, terminando em `/predict`.

Exemplo:

```text
PREDICTOR_URL=https://digitaltwin-predictor.onrender.com/predict
```
