# Streamlit

Painel de relatorios em tempo quase real.

O painel consome o historico diretamente do Firebase, incluindo a chave `prediction` criada pelo container `trigger`. Ele tambem tenta usar a API de metricas para preencher os cartoes derivados; se a API estiver indisponivel, calcula um resumo simples localmente.

A area principal do dashboard e atualizada automaticamente usando `st.fragment`, sem recarregar a pagina inteira. O intervalo padrao e 5 segundos, e o usuario pode trocar na lateral para 5, 15, 30 ou 60 segundos.

## Execucao

A partir da raiz do projeto:

```bash
docker compose up --build
```

Acesse:

```text
http://localhost:8501
```

## Configuracao dinamica

No menu lateral, o usuario pode alterar `horizon_steps`. Essa configuracao e gravada no Firebase em `digital_twin_runtime_config/prediction`.

O trigger le esse valor e aplica apenas nas proximas previsoes. O historico continua preservando o valor usado em cada registro dentro de `prediction.horizon_steps`, permitindo destacar no grafico onde a regra mudou.

## Variaveis

- `FIREBASE_HOST`: URL do Firebase Realtime Database.
- `FIREBASE_COLLECTION`: colecao dos registros.
- `RUNTIME_CONFIG_PATH`: caminho da configuracao dinamica.
- `METRICS_API_URL`: URL da API de metricas.
- `FETCH_LIMIT`: quantidade padrao de registros carregados.
- `APP_TIMEZONE`: fuso usado para interpretar timestamps sem timezone vindos do Arduino.
