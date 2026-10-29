// Replays synthetic IMU traces through imu::Detector. Built and run by tools/test_imu.py.
// 50 Hz samples, deterministic noise, gravity along +z when upright (the detector calibrates its own "up").
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include "imu_events.h"

using namespace imu;

struct Sim {
  Detector det;
  uint32_t t = 1000;
  uint32_t rng = 12345;
  std::vector<std::pair<uint32_t, Event>> ev;
  float noise() { rng = rng * 1664525u + 1013904223u; return ((rng >> 8) & 0xFFFF) / 65535.0f - 0.5f; }
  void push(Vec a, Vec g = {}) {
    a.x += 0.01f * noise(); a.y += 0.01f * noise(); a.z += 0.01f * noise();
    g.x += 1.0f * noise(); g.y += 1.0f * noise(); g.z += 1.0f * noise();
    Event e = det.update(t, a, g);
    if (e != NONE) ev.push_back({t, e});
    t += 20;
  }
  void hold(Vec a, float secs, Vec g = {}) { for (int i = 0; i < (int)(secs * 50); ++i) push(a, g); }
  int count(Event e) const { int n = 0; for (auto& p : ev) n += p.second == e; return n; }
  uint32_t first(Event e) const { for (auto& p : ev) if (p.second == e) return p.first; return 0; }
  void calibrate() {   // stand it up and let it learn "up" (as the firmware does)
    for (int i = 0; i < 200 && !det.calibrated(); ++i) {
      uint32_t before = t;
      Vec a{0.02f, -0.03f, 1.0f};
      a.x += 0.01f * noise();
      if (det.calibrate(t, a, {})) break;
      (void)before;
      t += 20;
    }
  }
  void clear() { ev.clear(); }
};

static int failures = 0;
#define CHECK(cond, msg) do { if (!(cond)) { std::printf("FAIL: %s  (%s:%d)\n", msg, __FILE__, __LINE__); ++failures; } } while (0)

static void report(const char* name, Sim& s) {
  std::printf("%-26s", name);
  for (auto& p : s.ev) std::printf(" %s@%.1fs", imu::name(p.second), (p.first - 1000) / 1000.0);
  std::printf("%s\n", s.ev.empty() ? " (no events)" : "");
}

static Vec UP{0.02f, -0.03f, 1.0f};
static Vec DOWNV{0.02f, -0.03f, -1.0f};      // upside down
static Vec SIDE{1.0f, -0.03f, 0.02f};        // lying on its side

int main() {
  {  // calibration needs stillness: a moving toy never calibrates
    Sim s;
    for (int i = 0; i < 300; ++i) { s.det.calibrate(s.t, {0.5f * s.noise(), 0.5f * s.noise(), 1.0f + 0.5f * s.noise()}, {50, 0, 0}); s.t += 20; }
    CHECK(!s.det.calibrated(), "calibrated while being moved");
    s.calibrate();
    CHECK(s.det.calibrated(), "did not calibrate while still");
    CHECK(s.det.upright().z > 0.99f, "upright vector wrong");
  }
  {  // carried upright, walking: nothing fires
    Sim s; s.calibrate();
    for (int i = 0; i < 500; ++i) {
      float ph = i * 0.02f * 6.28f * 2.0f;
      s.push({0.25f * std::sin(ph), 0.1f * std::sin(ph * 0.5f), 1.0f + 0.3f * std::sin(ph * 2)}, {30.f * std::sin(ph), 10, 0});
    }
    report("carried upright", s);
    CHECK(s.ev.empty(), "events while carried upright");
  }
  {  // carried sideways for 8 s, moving: must not count as sleeping
    Sim s; s.calibrate();
    for (int i = 0; i < 400; ++i) {
      float ph = i * 0.02f * 6.28f * 1.8f;
      s.push({1.0f + 0.1f * std::sin(ph), 0.12f * std::sin(ph), 0.1f * std::sin(ph * 2)}, {35.f * std::sin(ph), 20, 5});
    }
    report("carried sideways", s);
    CHECK(s.count(SLEEP) == 0, "carried sideways triggered sleep");
  }
  {  // lying on its side, still: sleep at ~3 s; then stood up: woken
    Sim s; s.calibrate(); s.hold(UP, 1.0);
    uint32_t t_side = s.t;
    s.hold(SIDE, 5.0);
    uint32_t sl = s.first(SLEEP);
    s.hold(UP, 2.0);
    report("sleep then wake", s);
    CHECK(s.count(SLEEP) == 1, "no sleep");
    CHECK(sl && sl - t_side > 2800 && sl - t_side < 4200, "sleep at the wrong time");
    CHECK(s.count(WOKEN) == 1, "no wake");
    CHECK(s.count(DROPPED) == 0, "a slow lie-down counted as dropped");
  }
  {  // briefly upside down (2 s): the upside-down reaction, not sleep
    Sim s; s.calibrate(); s.hold(UP, 1.0);
    s.hold(DOWNV, 2.0);
    s.hold(UP, 2.0);
    report("brief upside down", s);
    CHECK(s.count(UPSIDE_DOWN) == 1, "no upside-down event");
    CHECK(s.count(SLEEP) == 0, "brief upside down slept");
  }
  {  // upside down and stays: upside-down yell, then sleep
    Sim s; s.calibrate(); s.hold(UP, 1.0); s.hold(DOWNV, 6.0);
    report("inverted, stays", s);
    CHECK(s.count(UPSIDE_DOWN) == 1 && s.count(SLEEP) == 1, "inverted-and-stays should give both once");
  }
  {  // tossed: flight 300 ms, hard landing
    Sim s; s.calibrate(); s.hold(UP, 1.0);
    s.hold({0.05f, 0.05f, 0.1f}, 0.3, {120, 80, 40});
    s.push({0.5f, 0.2f, 3.2f}); s.push({0.2f, 0.1f, 1.8f}); s.hold(UP, 2.0);
    report("tossed", s);
    CHECK(s.count(TOSSED) == 1, "toss not detected once");
    CHECK(s.count(DROPPED) == 0 && s.count(SHAKEN) == 0 && s.count(SPUN) == 0, "toss also fired another event");
  }
  {  // long flight caught softly (improvement over the doc): still a toss
    Sim s; s.calibrate(); s.hold(UP, 1.0);
    s.hold({0.05f, 0.05f, 0.1f}, 0.35);
    s.push({0.2f, 0.1f, 1.7f}); s.hold(UP, 2.0);
    report("tossed, soft catch", s);
    CHECK(s.count(TOSSED) == 1, "soft catch not counted");
  }
  {  // short hop (50 ms of low g): not a toss
    Sim s; s.calibrate(); s.hold(UP, 1.0);
    s.hold({0.1f, 0.1f, 0.15f}, 0.04); s.push({0, 0, 2.4f}); s.hold(UP, 2.0);
    report("tiny hop", s);
    CHECK(s.count(TOSSED) == 0, "a 40 ms dip counted as a toss");
  }
  {  // dropped: one spike with no flight, then settles
    Sim s; s.calibrate(); s.hold(UP, 1.0);
    s.push({0.4f, 0.2f, 2.9f}); s.push({0.1f, 0.1f, 1.6f}); s.hold(UP, 2.0);
    report("dropped", s);
    CHECK(s.count(DROPPED) == 1, "drop not detected once");
    CHECK(s.count(TOSSED) == 0, "drop counted as toss");
  }
  {  // tipped over: upright -> side in 0.4 s with a 1.6 g bump, then still
    Sim s; s.calibrate(); s.hold(UP, 1.0);
    for (int i = 0; i < 20; ++i) { float f = i / 19.0f; s.push({f * 1.0f, -0.03f, 1.0f - f * 0.98f}, {60, 0, 0}); }
    s.push({1.5f, 0.1f, 0.5f}); s.push({1.2f, 0.f, 0.3f});   // it hits the floor
    s.hold(SIDE, 2.0);
    report("tipped over", s);
    CHECK(s.count(DROPPED) == 1, "tip not detected once");
  }
  {  // shaken: 5 Hz, +-1 g on x for 1.5 s
    Sim s; s.calibrate(); s.hold(UP, 1.0);
    for (int i = 0; i < 75; ++i) s.push({1.1f * std::sin(i * 0.02f * 6.28f * 5.f), 0.f, 1.f + 0.6f * std::sin(i * 0.02f * 6.28f * 5.f + 1)}, {80, 40, 0});
    s.hold(UP, 2.0);
    report("shaken", s);
    CHECK(s.count(SHAKEN) == 1, "shake not detected once");
    CHECK(s.count(DROPPED) == 0, "shake also counted as dropped");
  }
  {  // spun: 400 deg/s for 1 s
    Sim s; s.calibrate(); s.hold(UP, 1.0);
    s.hold(UP, 1.0, {0, 0, 400});
    s.hold(UP, 1.0);
    report("spun", s);
    CHECK(s.count(SPUN) == 1, "spin not detected once");
  }
  {  // rocked: 0.2 g sway at 0.8 Hz for 7 s
    Sim s; s.calibrate(); s.hold(UP, 1.0);
    for (int i = 0; i < 350; ++i) s.push({0.2f * std::sin(i * 0.02f * 6.28f * 0.8f), 0.f, 1.f}, {40, 0, 0});
    s.hold(UP, 1.0);
    report("rocked", s);
    CHECK(s.count(ROCKED) == 1, "rocking not detected once");
  }
  {  // a short sway (2 s) is not rocking
    Sim s; s.calibrate(); s.hold(UP, 1.0);
    for (int i = 0; i < 100; ++i) s.push({0.2f * std::sin(i * 0.02f * 6.28f * 0.8f), 0.f, 1.f}, {40, 0, 0});
    s.hold(UP, 2.0);
    report("short sway", s);
    CHECK(s.count(ROCKED) == 0, "2 s of sway counted as rocking");
  }
  {  // cooldown: two tosses 3 s apart, one event
    Sim s; s.calibrate(); s.hold(UP, 1.0);
    for (int k = 0; k < 2; ++k) { s.hold({0.05f, 0.05f, 0.1f}, 0.3); s.push({0.5f, 0.2f, 3.2f}); s.hold(UP, 2.5); }
    report("two tosses 3 s apart", s);
    CHECK(s.count(TOSSED) == 1, "cooldown did not apply");
  }
  {  // uncalibrated: no orientation events at all (but a toss still works)
    Sim s; s.hold(UP, 1.0); s.hold(SIDE, 6.0);
    report("uncalibrated lying", s);
    CHECK(s.count(SLEEP) == 0, "slept before calibration");
  }
  {  // regression (review): a state change that collides with another event on the same sample is deferred, never lost
    Sim s; s.calibrate(); s.hold(UP, 1.0); s.hold(SIDE, 4.0);
    s.push({0.3f, 0.1f, 2.6f}); s.hold(UP, 3.0);          // picked up, put down upright with a bump
    report("wake collides with drop", s);
    CHECK(s.count(SLEEP) == 1, "sleep lost");
    CHECK(s.count(WOKEN) == 1, "wake swallowed by a simultaneous event");
    CHECK(!s.det.asleep(), "detector stuck asleep");
  }
  {  // regression (review): millis() wraps at 2^32; a toss just before the wrap must not block later events
    Sim s; s.t = 0xFFFFFFFFu - 4500; s.calibrate(); s.hold(UP, 1.0);
    s.hold({0.05f, 0.05f, 0.1f}, 0.3, {120, 80, 40}); s.push({0.5f, 0.2f, 3.2f}); s.hold(UP, 2.5);   // crosses the wrap
    for (int i = 0; i < 75; ++i) s.push({1.1f * std::sin(i * 0.02f * 6.28f * 5.f), 0.f, 1.f + 0.6f * std::sin(i * 0.02f * 6.28f * 5.f + 1)}, {80, 40, 0});
    s.hold(UP, 2.0);
    report("across the millis wrap", s);
    CHECK(s.count(TOSSED) == 1, "toss lost around the wrap");
    CHECK(s.count(SHAKEN) == 1, "shake blocked after the wrap");
  }
  {  // regression (review): wobbling around the inverted threshold must not repeat the upside-down event
    Sim s; s.calibrate(); s.hold(UP, 1.0);
    for (int k = 0; k < 12; ++k) { s.hold({0.02f, -0.03f, -0.75f - 0.0f}, 1.0); s.hold({0.02f, -0.03f, -0.62f}, 1.0); }
    report("wobble at -0.7", s);
    CHECK(s.count(UPSIDE_DOWN) <= 1, "upside-down re-fired while wobbling");
  }
  {  // regression (review): re-calibration forgets stale state (asleep, filters)
    Sim s; s.calibrate(); s.hold(UP, 1.0); s.hold(SIDE, 4.0);
    CHECK(s.det.asleep(), "should be asleep");
    s.det.setUpright({1.0f, 0, 0});    // a parent re-calibrates with the toy lying down
    s.det.resetState();
    CHECK(!s.det.asleep(), "state not cleared by resetState");
    CHECK(s.det.calibrated(), "resetState must keep the pose");
  }
  std::printf(failures ? "\n%d FAILED\n" : "\nALL OK\n", failures);
  return failures ? 1 : 0;
}
