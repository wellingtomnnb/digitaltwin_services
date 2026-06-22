# Arduino

Contem o firmware `digital_twin_esp32.ino` usado no ESP32 para coletar dados dos sensores DS18B20, controlar o MOSFET e gravar as amostras no Firebase Realtime Database.

Este diretorio existe apenas para versionamento do firmware. A API consome os dados que esse firmware grava na colecao `digital_twin_dinamico_rev1`.

Resumo do firmware:

- Le dois sensores DS18B20: `ds18b201` como temperatura principal do resistor e `ds18b202` como temperatura ambiente.
- Gera `setpoint` aleatorio entre `30.0` e `38.0 °C` no boot e a cada 20 minutos.
- Usa histerese fixa de `1.0 °C` para evitar liga/desliga excessivo do MOSFET.
- Liga o MOSFET quando `ds18b201 < setpoint - hysteresis`.
- Desliga o MOSFET quando `ds18b201 > setpoint + hysteresis`.
- Envia uma amostra ao Firebase aproximadamente a cada 2 segundos.
- Usa o timestamp NTP como chave do registro no Firebase.
