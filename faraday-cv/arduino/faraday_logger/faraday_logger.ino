/*
 * faraday_logger -- induced-voltage logger for the pendulum experiment.
 *
 * Hardware
 *   Arduino UNO + ADS1115 16-bit ADC (I2C: A4 = SDA, A5 = SCL)
 *   Coil  -> ADS1115 AIN0 / AIN1 (differential, so the sign of the emf is kept)
 *   LED   -> D9 through a 220 ohm resistor, placed inside the camera's view
 *
 * What it does
 *   On 's' (or on the first serial connection) it lights the marker LED and
 *   starts streaming CSV:
 *
 *       t_ms,voltage_mV
 *       0.000,1.7031
 *       8.621,1.6875
 *
 *   t = 0 is the instant the LED was switched on.  The video analysis takes
 *   t = 0 to be the first frame in which that LED appears lit, which is what
 *   puts the two records on one time axis.  Send 'x' to stop, 's' to restart.
 *
 * Gain
 *   GAIN_SIXTEEN = +-0.256 V full scale, 7.8125 uV per bit.  A 7000-turn coil
 *   and a hand-swung magnet stay well inside that.  If the log clips at
 *   +-256 mV, step down to GAIN_EIGHT (+-0.512 V) or GAIN_FOUR (+-1.024 V).
 *
 * Rate
 *   RATE_ADS1115_128SPS gives ~116 effective samples per second once the I2C
 *   traffic and the serial printing are paid for -- the rate reported in the
 *   paper.  475 SPS works too if the sketch prints fewer digits.
 *
 * Library: Adafruit ADS1X15 (Library Manager -> "Adafruit ADS1X15").
 */

#include <Adafruit_ADS1X15.h>
#include <Wire.h>

Adafruit_ADS1115 ads;

const uint8_t LED_PIN = 9;      // marker LED, must be visible to the camera
const uint32_t BAUD = 115200;   // keep this in sync with the PC-side logger
const bool AUTOSTART = true;    // start logging as soon as the port opens

bool logging = false;
uint32_t t0_us = 0;

void printHeader() {
  Serial.println(F("# faraday-cv voltage log"));
  Serial.println(F("# ADS1115 differential AIN0-AIN1, GAIN_SIXTEEN (+-0.256 V)"));
  Serial.println(F("# t = 0 is the instant the marker LED was switched on"));
  Serial.println(F("t_ms,voltage_mV"));
}

void startLogging() {
  digitalWrite(LED_PIN, HIGH);  // the timing marker: light it first...
  t0_us = micros();             // ...then start the clock
  logging = true;
  printHeader();
}

void stopLogging() {
  logging = false;
  digitalWrite(LED_PIN, LOW);
  Serial.println(F("# stopped"));
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  Serial.begin(BAUD);
  while (!Serial) {
    ;  // wait for the USB serial port (Leonardo/Micro); no-op on the UNO
  }

  if (!ads.begin()) {
    Serial.println(F("# ERROR: no ADS1115 found on the I2C bus"));
    while (true) {
      digitalWrite(LED_PIN, HIGH);
      delay(120);
      digitalWrite(LED_PIN, LOW);
      delay(120);
    }
  }
  ads.setGain(GAIN_SIXTEEN);
  ads.setDataRate(RATE_ADS1115_128SPS);
  ads.startADCReading(ADS1X15_REG_CONFIG_MUX_DIFF_0_1, /*continuous=*/true);

  if (AUTOSTART) {
    delay(200);  // let the host settle before the marker frame is emitted
    startLogging();
  } else {
    Serial.println(F("# send 's' to start, 'x' to stop"));
  }
}

void loop() {
  if (Serial.available()) {
    char cmd = Serial.read();
    if (cmd == 's' && !logging) {
      startLogging();
    } else if (cmd == 'x' && logging) {
      stopLogging();
    }
  }

  if (!logging || !ads.conversionComplete()) {
    return;
  }

  int16_t raw = ads.getLastConversionResults();
  float mv = ads.computeVolts(raw) * 1000.0f;
  float t_ms = (micros() - t0_us) / 1000.0f;

  Serial.print(t_ms, 3);
  Serial.print(',');
  Serial.println(mv, 4);
}
