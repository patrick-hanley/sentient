/*
 * AtomS3R-CAM + Atomic Voice Base — combined smoke test
 * -----------------------------------------------------
 * One upload proves every subsystem the sentient toys need:
 *   1. Camera  -> live MJPEG stream in a browser (Sage's eyes)
 *   2. Mic     -> continuously buffered through the Voice Base (the ears)
 *   3. Speaker -> press the Atom's front button, the last ~3 seconds
 *                 of buffered audio play back (the mouth)
 *
 * Hardware: AtomS3R-CAM head stacked on its Atomic Voice Base, USB-C power.
 * Pins: GC0308 camera map from M5Stack's AtomS3R-CAM datasheet.
 * Audio pattern: M5Stack's own Atom VoiceS3R M5Unified mic example —
 * mic and speaker share the ES8311 codec, so they take turns
 * (Speaker.end/Mic.begin and back). Half-duplex is by design here,
 * and it matches the toys' one-live-mic-at-a-time director model.
 *
 * Arduino IDE setup (once):
 *   - Board: M5AtomS3R (M5Stack board package)
 *   - PSRAM: "OPI PSRAM" / Enabled        (frame buffer lives there)
 *   - USB CDC On Boot: Enabled            (so Serial Monitor works)
 *   - Library: M5Unified (Library Manager; pulls in M5GFX itself)
 *   - esp_camera ships with the ESP32 core — nothing extra to install.
 * Upload trouble? Hold the reset button ~2 s until the green LED
 * lights, release — that's download mode on this head.
 */

#include <M5Unified.h>
#include <WiFi.h>
#include <esp_camera.h>
#include <esp_http_server.h>
#include "img_converters.h"

// ---------- fill these in ----------
static const char* WIFI_SSID = "YOUR_WIFI_NAME";
static const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
// -----------------------------------

// GC0308 camera pins — AtomS3R-CAM (M5Stack datasheet pin map)
#define CAM_SIOD   12   // SCCB data
#define CAM_SIOC    9   // SCCB clock
#define CAM_VSYNC  10
#define CAM_HREF   14
#define CAM_XCLK   21
#define CAM_PCLK   40
#define CAM_Y2      3   // D0
#define CAM_Y3     42   // D1
#define CAM_Y4     46   // D2
#define CAM_Y5     48   // D3
#define CAM_Y6      4   // D4
#define CAM_Y7     17   // D5
#define CAM_Y8     11   // D6
#define CAM_Y9     13   // D7
#define CAM_POWER  18   // camera power enable, ACTIVE LOW

// ---------- mic ring buffer (M5Stack's VoiceS3R pattern) ----------
static constexpr const size_t record_number    = 256;
static constexpr const size_t record_length    = 200;
static constexpr const size_t record_size      = record_number * record_length;
static constexpr const size_t record_samplerate = 16000;
static size_t rec_record_idx = 2;
static int16_t* rec_data = nullptr;

// ---------- MJPEG stream plumbing (Espressif CameraWebServer pattern) ----------
#define PART_BOUNDARY "123456789000000000000987654321"
static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* _STREAM_BOUNDARY     = "\r\n--" PART_BOUNDARY "\r\n";
static const char* _STREAM_PART         = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

static esp_err_t stream_handler(httpd_req_t* req) {
  camera_fb_t* fb = nullptr;
  esp_err_t res = ESP_OK;
  size_t jpg_buf_len = 0;
  uint8_t* jpg_buf = nullptr;
  char part_buf[64];

  res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
  if (res != ESP_OK) return res;

  while (true) {
    fb = esp_camera_fb_get();
    if (!fb) {
      res = ESP_FAIL;
    } else if (fb->format != PIXFORMAT_JPEG) {
      bool ok = frame2jpg(fb, 80, &jpg_buf, &jpg_buf_len);
      esp_camera_fb_return(fb);
      fb = nullptr;
      if (!ok) res = ESP_FAIL;
    } else {
      jpg_buf_len = fb->len;
      jpg_buf = fb->buf;
    }
    if (res == ESP_OK) {
      size_t hlen = snprintf(part_buf, sizeof(part_buf), _STREAM_PART, jpg_buf_len);
      res = httpd_resp_send_chunk(req, part_buf, hlen);
    }
    if (res == ESP_OK) res = httpd_resp_send_chunk(req, (const char*)jpg_buf, jpg_buf_len);
    if (res == ESP_OK) res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
    if (fb) { esp_camera_fb_return(fb); fb = nullptr; jpg_buf = nullptr; }
    else if (jpg_buf) { free(jpg_buf); jpg_buf = nullptr; }
    if (res != ESP_OK) break;
  }
  return res;
}

static const char INDEX_HTML[] =
  "<!doctype html><html><head><meta charset='utf-8'><title>Atom Toy Test</title></head>"
  "<body style='font-family:sans-serif;background:#111;color:#eee;text-align:center'>"
  "<h2>AtomS3R-CAM &mdash; camera live</h2>"
  "<img src='/stream' style='max-width:90vw;border:1px solid #444'>"
  "<p>Mic is buffering continuously. Press the Atom's front button:<br>"
  "the last ~3 seconds of audio play back through the Voice Base speaker.</p>"
  "</body></html>";

static esp_err_t index_handler(httpd_req_t* req) {
  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, INDEX_HTML, strlen(INDEX_HTML));
}

static bool init_camera() {
  // Camera rail is gated by GPIO18 — pull LOW to power the sensor.
  pinMode(CAM_POWER, OUTPUT);
  digitalWrite(CAM_POWER, LOW);
  delay(50);

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = CAM_Y2;
  config.pin_d1 = CAM_Y3;
  config.pin_d2 = CAM_Y4;
  config.pin_d3 = CAM_Y5;
  config.pin_d4 = CAM_Y6;
  config.pin_d5 = CAM_Y7;
  config.pin_d6 = CAM_Y8;
  config.pin_d7 = CAM_Y9;
  config.pin_xclk     = CAM_XCLK;
  config.pin_pclk     = CAM_PCLK;
  config.pin_vsync    = CAM_VSYNC;
  config.pin_href     = CAM_HREF;
  config.pin_sccb_sda = CAM_SIOD;
  config.pin_sccb_scl = CAM_SIOC;
  config.pin_pwdn     = -1;
  config.pin_reset    = -1;
  // M5Unified already owns I2C bus 1 (codec/IMU) by the time we get here,
  // and the camera's SCCB driver defaults to bus 1 too -> 0x103 conflict.
  // The camera's SCCB pins (12/9) are its own pair, so give SCCB bus 0.
  config.sccb_i2c_port = 0;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size   = FRAMESIZE_VGA;   // 640x480 — GC0308's max
  config.jpeg_quality = 12;
  config.fb_count     = 2;
  config.fb_location  = CAMERA_FB_IN_PSRAM;
  config.grab_mode    = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init FAILED: 0x%x\n", err);
    return false;
  }
  Serial.println("Camera init OK");
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(300);
  M5.begin();
  M5.Speaker.setVolume(200);

  rec_data = (int16_t*)heap_caps_malloc(record_size * sizeof(int16_t), MALLOC_CAP_8BIT);
  memset(rec_data, 0, record_size * sizeof(int16_t));

  // Speaker off, mic on (shared codec — they take turns).
  M5.Speaker.end();
  M5.Mic.begin();

  if (!init_camera()) {
    Serial.println("Continuing without camera — audio test still works.");
  }

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi connecting");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println();

  httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
  cfg.server_port = 80;
  httpd_handle_t server = nullptr;
  if (httpd_start(&server, &cfg) == ESP_OK) {
    httpd_uri_t index_uri  = { "/",      HTTP_GET, index_handler,  nullptr };
    httpd_uri_t stream_uri = { "/stream", HTTP_GET, stream_handler, nullptr };
    httpd_register_uri_handler(server, &index_uri);
    httpd_register_uri_handler(server, &stream_uri);
  }

  Serial.printf("\n=== ATOM TOY TEST READY ===\nOpen http://%s/ in a browser for the camera.\n",
                WiFi.localIP().toString().c_str());
  Serial.println("Talk, then press the Atom's button to hear it played back.");
}

void loop() {
  M5.update();

  if (M5.Mic.isEnabled()) {
    auto data = &rec_data[rec_record_idx * record_length];
    if (M5.Mic.record(data, record_length, record_samplerate)) {
      if (++rec_record_idx >= record_number) rec_record_idx = 0;
    }
  }

  if (M5.BtnA.wasClicked()) {
    if (M5.Speaker.isEnabled()) {   // matches M5Stack's VoiceS3R example verbatim
      while (M5.Mic.isRecording()) M5.delay(1);
      M5.Mic.end();
      M5.Speaker.begin();

      int start_pos = rec_record_idx * record_length;
      if (start_pos < (int)record_size) {
        M5.Speaker.playRaw(&rec_data[start_pos], record_size - start_pos,
                           record_samplerate, false, 1, 0);
      }
      if (start_pos > 0) {
        M5.Speaker.playRaw(rec_data, start_pos, record_samplerate, false, 1, 0);
      }
      do { M5.delay(1); M5.update(); } while (M5.Speaker.isPlaying());

      M5.Speaker.end();
      M5.Mic.begin();
      Serial.println("Playback done — mic live again.");
    }
  }
}
