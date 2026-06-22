# Streamlit

Diretorio reservado para o painel de relatorios.

O painel deve consumir o historico diretamente do Firebase, incluindo a chave `prediction` criada pelo container `trigger`.

Quando o usuario alterar parametros como `horizon_steps`, a mudanca deve valer para os proximos registros. O historico pode destacar o ponto da troca usando o valor salvo em `prediction.horizon_steps`.
