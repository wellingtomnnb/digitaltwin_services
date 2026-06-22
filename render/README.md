# Render

Blueprint de deploy do projeto no Render.

## Estrutura

- `digitaltwin-streamlit`: web service público, porta única exposta.
- `digitaltwin-metrics`: private service para as métricas do controlador.
- `digitaltwin-predictor`: serviço privado para atender o trigger.
- `digitaltwin-trigger`: background worker que lê o Firebase e grava `prediction`.

## Como usar

No Render, crie um projeto via Blueprint apontando para `render.yaml` na raiz do repositorio.

## Observacoes

- O painel Streamlit consome a API de métricas pela rede privada do Render.
- O `trigger` precisa do `predictor` rodando para preencher as previsoes no Firebase.
- O `predictor` nao precisa ser exposto ao publico, porque só o `trigger` o consome.
