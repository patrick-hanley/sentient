/*
 * Sentient toys — thin Atom client (same firmware on Pip, Sage, Noodle)
 * ---------------------------------------------------------------------
 * The brain is off-board; this sketch only moves bytes:
 *   ears  : mic 16 kHz mono int16 -> UDP packets to the brain (port 5005)
 *   eyes  : GET  /capture  -> one QVGA JPEG (brain polls 1–2 fps)
 *   mouth : POST /play[?fmt=ulaw&rate=16000] -> mono audio, int16 LE PCM (default) or
 *           8-bit G.711 mu-law (half the bytes); replies when playback is done
 *   other : GET  /status   -> one-line JSON
 *           button click / hold -> "BTN click" / "BTN hold" over UDP
 * The brain tells toys apart by MAC address, so all three Atoms run this
 * exact binary.
 *
 * Discovery: the Atom broadcasts "HELLO <mac> cam=<0|1> mic=<0|1> spk=<0|1>"
 * to UDP 5005 every 3 s. The brain answers "ACK" to UDP 5006, and mic
 * packets then go unicast to whoever sent the last ACK.
 * Mic packet: 'M' + uint16 seq (LE) + 320 int16 samples (20 ms) = 643 bytes.
 *
 * Half-duplex by hardware (mic and speaker share the ES8311): while /play
 * audio is playing, the mic is off and no mic packets are sent.
 *
 * Arduino IDE: board M5AtomS3R, PSRAM "OPI PSRAM", USB CDC On Boot Enabled,
 * library M5Unified. Serial 115200.
 * Upload trouble? Hold reset ~2 s until the green LED lights = download mode.
 */

#include <M5Unified.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <Preferences.h>
#include <Wire.h>
#include <esp_camera.h>
#include <esp_http_server.h>
#include <esp_mac.h>
#include "img_converters.h"

// ---------- Wi-Fi: secrets.h (git-ignored; copy secrets.example.h) ----------
struct WifiCred { const char* ssid; const char* pass; };
#include "secrets.h"
static constexpr uint16_t BRAIN_PORT = 5005;
static constexpr uint16_t ATOM_PORT  = 5006;
static constexpr const char* FW_VERSION = "toy-client-2";

// ---------- GC0308 camera pins — AtomS3R-CAM ----------
#define CAM_SIOD   12
#define CAM_SIOC    9
#define CAM_VSYNC  10
#define CAM_HREF   14
#define CAM_XCLK   21
#define CAM_PCLK   40
#define CAM_Y2      3
#define CAM_Y3     42
#define CAM_Y4     46
#define CAM_Y5     48
#define CAM_Y6      4
#define CAM_Y7     17
#define CAM_Y8     11
#define CAM_Y9     13
#define CAM_POWER  18   // camera power enable, ACTIVE LOW

// ---------- audio ----------
static constexpr uint32_t SAMPLE_RATE  = 16000;
static constexpr size_t   FRAME        = 320;            // 20 ms
static constexpr size_t   RING         = 8;
static constexpr size_t   PLAY_MAX     = SAMPLE_RATE * 30; // 30 s of speech
static int16_t* mic_ring   = nullptr;
static size_t   ring_idx   = 0;
static size_t   frames_rec = 0;
static uint16_t mic_seq    = 0;

static int16_t*        play_buf     = nullptr;
static volatile size_t play_len     = 0;      // samples
static volatile bool   play_pending = false;
static volatile bool   playing      = false;
static volatile bool   rx_busy      = false;  // /play upload in progress: stop mic UDP so it doesn't eat airtime
static volatile uint32_t play_rate  = SAMPLE_RATE;

static WiFiUDP udp;
static IPAddress brain_ip;
static bool      brain_known = false;
static uint32_t  last_hello = 0;
static uint32_t  last_ack   = 0;
static char      mac_str[18];

static bool cam_ok = false;
static int  cam_port = -1;
static Preferences prefs;

// ---------- camera ----------
static bool init_camera_on(int port) {
  pinMode(CAM_POWER, OUTPUT);
  digitalWrite(CAM_POWER, LOW);
  delay(50);

  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer   = LEDC_TIMER_0;
  c.pin_d0 = CAM_Y2; c.pin_d1 = CAM_Y3; c.pin_d2 = CAM_Y4; c.pin_d3 = CAM_Y5;
  c.pin_d4 = CAM_Y6; c.pin_d5 = CAM_Y7; c.pin_d6 = CAM_Y8; c.pin_d7 = CAM_Y9;
  c.pin_xclk  = CAM_XCLK;  c.pin_pclk = CAM_PCLK;
  c.pin_vsync = CAM_VSYNC; c.pin_href = CAM_HREF;
  // esp32-camera is built with SCCB on I2C port 1 when given its own pins, but
  // port 1 is the ES8311 codec's bus (M5Unified) — the mic goes silent. So we
  // open port 0 (Wire) on the camera's pins and hand the camera that bus.
  if (port == 0) {
    Wire.end();
    Wire.begin(CAM_SIOD, CAM_SIOC, 100000);
    c.pin_sccb_sda = -1; c.pin_sccb_scl = -1;
  } else {
    c.pin_sccb_sda = CAM_SIOD; c.pin_sccb_scl = CAM_SIOC;
  }
  c.pin_pwdn = -1; c.pin_reset = -1;
  c.sccb_i2c_port = port;
  c.xclk_freq_hz = 10000000;   // 20 MHz gave torn frames (FB-SIZE mismatch) under Wi-Fi load
  c.pixel_format = PIXFORMAT_RGB565;  // GC0308 has no JPEG encoder: capture RGB565, encode in /capture
  c.frame_size   = FRAMESIZE_QVGA;    // 320x240: plenty for faces/tags, light on Wi-Fi
  c.fb_count     = 2;
  c.fb_location  = CAMERA_FB_IN_PSRAM;
  c.grab_mode    = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&c);
  if (err != ESP_OK) {
    Serial.printf("Camera init FAILED on SCCB port %d: 0x%x\n", port, err);
    esp_camera_deinit();
    return false;
  }
  Serial.printf("Camera init OK (SCCB port %d)\n", port);
  cam_port = port;
  return true;
}

// ---------- HTTP ----------
static esp_err_t capture_handler(httpd_req_t* req) {
  if (!cam_ok) { httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "no camera"); return ESP_FAIL; }
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) { httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "fb"); return ESP_FAIL; }
  uint8_t* jpg = nullptr;
  size_t jpg_len = 0;
  bool ok = frame2jpg(fb, 80, &jpg, &jpg_len);
  esp_camera_fb_return(fb);
  if (!ok) { httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "jpeg"); return ESP_FAIL; }
  httpd_resp_set_type(req, "image/jpeg");
  esp_err_t res = httpd_resp_send(req, (const char*)jpg, jpg_len);
  free(jpg);
  return res;
}

static inline int16_t ulaw_decode(uint8_t u) {
  u = ~u;
  int t = ((u & 0x0F) << 3) + 0x84;
  t <<= (u & 0x70) >> 4;
  return (u & 0x80) ? (0x84 - t) : (t - 0x84);
}

static int query_int(httpd_req_t* req, const char* key, int dflt) {
  char q[64], v[16];
  if (httpd_req_get_url_query_str(req, q, sizeof(q)) == ESP_OK && httpd_query_key_value(q, key, v, sizeof(v)) == ESP_OK)
    return atoi(v);
  return dflt;
}

static bool query_is(httpd_req_t* req, const char* key, const char* want) {
  char q[64], v[16];
  return httpd_req_get_url_query_str(req, q, sizeof(q)) == ESP_OK &&
         httpd_query_key_value(q, key, v, sizeof(v)) == ESP_OK && strcmp(v, want) == 0;
}

// Blocking by design: waits for any line already playing, plays this one, and
// replies only when the speaker is done — the brain unmutes mics on our reply.
static esp_err_t play_handler(httpd_req_t* req) {
  uint32_t t0 = millis();
  while ((play_pending || playing) && millis() - t0 < 30000) delay(10);
  rx_busy = true;
  const bool ulaw = query_is(req, "fmt", "ulaw");
  const uint32_t rate = query_int(req, "rate", SAMPLE_RATE);
  const size_t bps = ulaw ? 1 : 2;                       // bytes per sample on the wire
  size_t samples = req->content_len / bps;
  if (samples > PLAY_MAX) samples = PLAY_MAX;
  size_t got = 0;                                        // samples stored
  uint8_t chunk[1024];
  size_t total = 0;                                      // bytes read
  while (total < req->content_len) {
    size_t want = req->content_len - total;
    if (want > sizeof(chunk)) want = sizeof(chunk);
    if (!ulaw && want % 2) want -= 1;
    if (want == 0) want = 1;
    int r = httpd_req_recv(req, (char*)chunk, want);
    if (r == HTTPD_SOCK_ERR_TIMEOUT) continue;
    if (r <= 0) { rx_busy = false; httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "recv"); return ESP_FAIL; }
    total += r;
    if (ulaw) {
      for (int i = 0; i < r && got < samples; ++i) play_buf[got++] = ulaw_decode(chunk[i]);
    } else {
      for (int i = 0; i + 1 < r && got < samples; i += 2) play_buf[got++] = (int16_t)(chunk[i] | (chunk[i + 1] << 8));
    }
  }
  play_len = got;
  play_rate = rate;
  play_pending = true;                       // loop() picks it up (mic/speaker switch stays on one task)
  uint32_t limit = millis() + play_len * 1000 / rate + 5000;
  while ((play_pending || playing) && millis() < limit) delay(5);
  rx_busy = false;
  char msg[32];
  snprintf(msg, sizeof(msg), "OK %u ms", (unsigned)(play_len * 1000 / rate));
  httpd_resp_set_type(req, "text/plain");
  return httpd_resp_send(req, msg, strlen(msg));
}

static esp_err_t status_handler(httpd_req_t* req) {
  char js[200];
  snprintf(js, sizeof(js),
           "{\"mac\":\"%s\",\"fw\":\"%s\",\"cam\":%d,\"cam_port\":%d,\"mic\":%d,\"spk\":%d,\"playing\":%d,\"rssi\":%d}",
           mac_str, FW_VERSION, cam_ok, cam_port, M5.Mic.isEnabled(), M5.Speaker.isEnabled(),
           (int)(playing || play_pending), WiFi.RSSI());
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_send(req, js, strlen(js));
}

static void start_http() {
  httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
  cfg.server_port = 80;
  cfg.recv_wait_timeout = 10;
  httpd_handle_t server = nullptr;
  if (httpd_start(&server, &cfg) != ESP_OK) { Serial.println("HTTP server FAILED"); return; }
  httpd_uri_t cap = { "/capture", HTTP_GET,  capture_handler, nullptr };
  httpd_uri_t ply = { "/play",    HTTP_POST, play_handler,    nullptr };
  httpd_uri_t sts = { "/status",  HTTP_GET,  status_handler,  nullptr };
  httpd_register_uri_handler(server, &cap);
  httpd_register_uri_handler(server, &ply);
  httpd_register_uri_handler(server, &sts);
}

// ---------- Wi-Fi ----------
static void connect_wifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);   // modem sleep adds 100+ ms jitter to UDP audio
  while (true) {
    for (const auto& w : WIFI_LIST) {
      Serial.printf("WiFi: trying %s", w.ssid);
      WiFi.begin(w.ssid, w.pass);
      for (int i = 0; i < 20 && WiFi.status() != WL_CONNECTED; ++i) { delay(500); Serial.print("."); }
      if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\nWiFi OK: %s  IP %s\n", w.ssid, WiFi.localIP().toString().c_str());
        return;
      }
      Serial.printf(" no (status %d)\n", (int)WiFi.status());
      WiFi.disconnect(true);
      delay(200);
    }
    // Nothing joined: show what 2.4 GHz networks this Atom can actually see.
    int n = WiFi.scanNetworks();
    Serial.printf("WiFi scan: %d networks (2.4 GHz only)\n", n);
    for (int i = 0; i < n && i < 15; ++i)
      Serial.printf("  %-28s ch%-2d %4d dBm auth=%d\n", WiFi.SSID(i).c_str(), WiFi.channel(i), WiFi.RSSI(i), (int)WiFi.encryptionType(i));
    WiFi.scanDelete();
  }
}

static void send_text(const IPAddress& ip, const char* s) {
  udp.beginPacket(ip, BRAIN_PORT);
  udp.write((const uint8_t*)s, strlen(s));
  udp.endPacket();
}

static void service_udp() {
  uint32_t now = millis();
  if (now - last_hello > 3000) {
    last_hello = now;
    char h[96];
    snprintf(h, sizeof(h), "HELLO %s cam=%d mic=%d spk=%d fw=%s",
             mac_str, cam_ok, M5.Mic.isEnabled(), M5.Speaker.isEnabled(), FW_VERSION);
    send_text(IPAddress(255, 255, 255, 255), h);
    if (brain_known) send_text(brain_ip, h);
  }
  if (brain_known && now - last_ack > 15000) {
    brain_known = false;
    Serial.println("Brain lost — back to broadcast");
  }
  int n = udp.parsePacket();
  while (n > 0) {
    char buf[32] = {0};
    udp.read(buf, sizeof(buf) - 1);
    if (strncmp(buf, "ACK", 3) == 0) {
      if (!brain_known || brain_ip != udp.remoteIP())
        Serial.printf("HELLO ack from brain %s\n", udp.remoteIP().toString().c_str());
      brain_ip = udp.remoteIP();
      brain_known = true;
      last_ack = now;
    }
    n = udp.parsePacket();
  }
}

// ---------- audio ----------
static void mic_on()  { M5.Speaker.end(); M5.Mic.begin(); frames_rec = 0; }
static void spk_on()  { while (M5.Mic.isRecording()) M5.delay(1); M5.Mic.end(); M5.Speaker.begin(); }

static void do_playback() {
  playing = true;
  play_pending = false;
  spk_on();
  M5.Speaker.playRaw(play_buf, play_len, play_rate, false, 1, 0);
  while (M5.Speaker.isPlaying()) { M5.delay(1); service_udp(); }
  mic_on();
  playing = false;
  if (brain_known) send_text(brain_ip, "PLAYED");
}

static void stream_mic() {
  if (!M5.Mic.isEnabled()) { delay(5); return; }
  int16_t* slot = &mic_ring[ring_idx * FRAME];
  if (!M5.Mic.record(slot, FRAME, SAMPLE_RATE)) return;
  // record() only returns once a queue slot frees, so the frame two
  // behind this one is complete.
  if (++frames_rec > 2 && brain_known && !rx_busy) {
    size_t done = (ring_idx + RING - 2) % RING;
    uint8_t pkt[3 + FRAME * 2];
    pkt[0] = 'M';
    pkt[1] = mic_seq & 0xFF;
    pkt[2] = mic_seq >> 8;
    memcpy(pkt + 3, &mic_ring[done * FRAME], FRAME * 2);
    udp.beginPacket(brain_ip, BRAIN_PORT);
    udp.write(pkt, sizeof(pkt));
    udp.endPacket();
    ++mic_seq;
  }
  ring_idx = (ring_idx + 1) % RING;
}

// Proves the codec really answers (isEnabled() only reflects config) and the camera delivers frames.
static void boot_selftest() {
  if (play_buf && M5.Mic.isEnabled()) {
    for (int i = 0; i < 2; ++i) M5.Mic.record(play_buf, 8000, SAMPLE_RATE);   // 2nd half-second, after settle
    while (M5.Mic.isRecording()) M5.delay(1);
    double acc = 0; int peak = 0;
    for (int i = 0; i < 8000; ++i) { int v = play_buf[i]; acc += (double)v * v; peak = max(peak, abs(v)); }
    Serial.printf("Mic self-test: rms=%d peak=%d  (0/0 = codec not responding)\n", (int)sqrt(acc / 8000), peak);
  }
  spk_on();
  M5.Speaker.tone(880, 120);  M5.delay(160);
  M5.Speaker.tone(1320, 160); M5.delay(220);
  mic_on();
  Serial.println("Speaker self-test: two-note chirp played");
  if (cam_ok) {
    camera_fb_t* fb = esp_camera_fb_get();
    if (fb) { Serial.printf("Camera frame OK %ux%u (%u bytes)\n", fb->width, fb->height, fb->len); esp_camera_fb_return(fb); }
    else Serial.println("Camera frame FAILED");
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.printf("\n=== %s boot ===\n", FW_VERSION);

  prefs.begin("toy", false);
  bool cam_first = prefs.getBool("camfirst", false);
#ifdef TOY_NO_CAMERA
  cam_first = true;   // diagnostic build: skip the camera entirely
  auto init_camera_on = [](int) { return false; };
#endif

  // Fallback path: camera before M5.begin() (set automatically after a failed boot).
  if (cam_first) {
    Serial.println("Camera-first boot order");
    cam_ok = init_camera_on(0) || init_camera_on(1);
  }

  auto cfg = M5.config();
  cfg.external_speaker.atomic_echo = true;   // Voice/Echo Base ES8311 — without this mic+speaker stay off
  M5.begin(cfg);
  Serial.printf("Board id %d\n", (int)M5.getBoard());
  {
    // The ES8311 puts its ADC data in the I2S slot M5Unified's mono mode doesn't
    // read (mono = all zeros). Capture stereo; record(..., mono) mixes it down.
    auto mc = M5.Mic.config();
    mc.stereo = true;
    M5.Mic.config(mc);
  }
  M5.Speaker.setVolume(200);

  if (!cam_first) {
    cam_ok = init_camera_on(0) || init_camera_on(1);
    if (!cam_ok) {
      Serial.println("Camera failed in both ports — rebooting with camera-first order");
      prefs.putBool("camfirst", true);
      delay(200);
      ESP.restart();
    }
  } else if (!cam_ok) {
    // Both orders failed: run audio-only, try normal order next boot.
    prefs.putBool("camfirst", false);
    Serial.println("Camera unavailable — running audio-only (toy has 'eyes closed')");
  }
  prefs.end();

  mic_ring = (int16_t*)heap_caps_calloc(RING * FRAME, sizeof(int16_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  play_buf = (int16_t*)heap_caps_malloc(PLAY_MAX * sizeof(int16_t), MALLOC_CAP_SPIRAM);
  if (!mic_ring || !play_buf) Serial.println("ALLOC FAILED (is PSRAM = OPI PSRAM?)");

  mic_on();
  Serial.println(M5.Mic.isEnabled()     ? "Mic enabled"     : "Mic DISABLED");
  Serial.println(M5.Speaker.isEnabled() ? "Speaker enabled" : "Speaker DISABLED");
  boot_selftest();

  uint8_t m[6];
  esp_read_mac(m, ESP_MAC_WIFI_STA);   // eFuse MAC; WiFi.macAddress() is junk before Wi-Fi starts
  snprintf(mac_str, sizeof(mac_str), "%02X:%02X:%02X:%02X:%02X:%02X", m[0], m[1], m[2], m[3], m[4], m[5]);
  Serial.printf("MAC %s\n", mac_str);

  connect_wifi();
  udp.begin(ATOM_PORT);
  start_http();
  Serial.printf("=== READY  http://%s/capture  /status ===\n", WiFi.localIP().toString().c_str());
}

void loop() {
  M5.update();
  if (WiFi.status() != WL_CONNECTED) { Serial.println("WiFi dropped"); connect_wifi(); }
  service_udp();

  if (play_pending) do_playback();
  stream_mic();

  if (M5.BtnA.wasHold() && brain_known)    send_text(brain_ip, "BTN hold");
  if (M5.BtnA.wasClicked() && brain_known) send_text(brain_ip, "BTN click");
}
