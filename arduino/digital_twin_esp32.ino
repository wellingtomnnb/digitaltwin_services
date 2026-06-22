#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>
#include <OneWire.h>
#include <DallasTemperature.h>

// ================= PINOS =================
#define ONE_WIRE_BUS 4
#define MOSFET_PIN 23

// ================= WIFI =================
#define WIFI_SSID "XXXXX"
#define WIFI_PASSWORD "XXXXX"

// ================= FIREBASE =================
#define FIREBASE_HOST "https://XXXXX.firebaseio.com"

// ================= SENSORES =================
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);

// ================= CONTROLE =================
float setpoint = 34.0;
float hysteresis = 1.0;
bool estadoMosfet = false;

// ================= TIMERS =================
unsigned long lastSetpointUpdate = 0;
unsigned long setpointInterval = 20UL * 60UL * 1000UL; // 20 minutos

// ================= STATUS =================
void status(String msg) {
  Serial.print("[");
  Serial.print(millis() / 1000);
  Serial.print("s] ");
  Serial.println(msg);
}

// ================= WIFI =================
void connectWiFi() {
  status("Conectando WiFi");

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.print(".");
  }

  Serial.println();
  status("WiFi conectado");
  Serial.println(WiFi.localIP());
}

// ================= SETPOINT ALEATORIO =================
void updateSetpoint() {
  // gera entre 30 e 38
  setpoint = random(300, 381) / 10.0;

  status("Novo setpoint: " + String(setpoint));
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);
  delay(2000);

  status("BOOT");

  // MOSFET
  pinMode(MOSFET_PIN, OUTPUT);
  digitalWrite(MOSFET_PIN, LOW);

  // Sensores
  sensors.begin();

  // WiFi
  connectWiFi();

  // NTP
  configTime(-3 * 3600, 0, "pool.ntp.org");

  struct tm timeinfo;
  while (!getLocalTime(&timeinfo)) {
    Serial.println("Aguardando NTP...");
    delay(1000);
  }

  status("Horario sincronizado");

  // Seed do random
  randomSeed(esp_random());

  // Inicializa setpoint
  updateSetpoint();
}

// ================= LOOP =================
void loop() {

  // Reconectar WiFi
  if (WiFi.status() != WL_CONNECTED) {
    status("WiFi caiu");
    WiFi.disconnect();
    connectWiFi();
  }

  // Atualizar setpoint a cada 20 min
  if (millis() - lastSetpointUpdate > setpointInterval) {
    lastSetpointUpdate = millis();
    updateSetpoint();
  }

  // Ler sensores
  sensors.requestTemperatures();

  float t1 = sensors.getTempCByIndex(0);
  float t2 = sensors.getTempCByIndex(1);

  // Limites com histerese
  float tempLiga = setpoint - hysteresis;
  float tempDesliga = setpoint + hysteresis;

  // ================= CONTROLE =================
  if (!estadoMosfet && t1 < tempLiga) {
    digitalWrite(MOSFET_PIN, HIGH);
    estadoMosfet = true;
    status("MOSFET LIGADO");
  }

  if (estadoMosfet && t1 > tempDesliga) {
    digitalWrite(MOSFET_PIN, LOW);
    estadoMosfet = false;
    status("MOSFET DESLIGADO");
  }

  // ================= NTP =================
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) {
    status("Erro NTP");
    delay(2000);
    return;
  }

  char timestamp[20];
  strftime(timestamp, sizeof(timestamp), "%Y-%m-%d %H:%M:%S", &timeinfo);

  // ================= FIREBASE ID =================
  String firebaseId = String(timestamp);
  firebaseId.replace(" ", "_");
  firebaseId.replace(":", "-");

  // ================= JSON =================
  String json = "{";
  json += "\"timestamp\":\"" + String(timestamp) + "\",";
  json += "\"setpoint\":" + String(setpoint) + ",";
  json += "\"ds18b201\":" + String(t1) + ",";
  json += "\"ds18b202\":" + String(t2) + ",";
  json += "\"mosfet\":" + String(estadoMosfet ? 1 : 0);
  json += "}";

  // ================= SERIAL =================
  Serial.println(json);

  // ================= FIREBASE =================
  String url = String(FIREBASE_HOST) + "/digital_twin_dinamico_rev1/" + firebaseId + ".json";

  HTTPClient http;
  http.begin(url.c_str());
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(5000);

  int httpResponseCode = http.PUT(json);

  Serial.print("HTTP Response: ");
  Serial.println(httpResponseCode);

  http.end();

  delay(2000); // ciclo de 2 segundos
}