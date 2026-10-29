// Motion events from an IMU, for the plush toys. Pure C++ (no Arduino/M5 includes) so tools/test_imu.py can
// compile it on the Mac and replay synthetic traces. See docs/imu-sounds.md for the design.
//
// Feed one sample at a time: update(t_ms, accel_g, gyro_dps). Returns at most one event per call.
// Nothing fires on a single sample: every event has a hold time, and a toy that is merely carried must not trigger.
#pragma once
#include <cmath>
#include <cstdint>

namespace imu {

// wrap-safe: true when t is at or after x (uint32 millis wrap every 49 days)
inline bool reached(uint32_t t, uint32_t x) { return (int32_t)(t - x) >= 0; }

enum Event : uint8_t { NONE = 0, SLEEP, WOKEN, TOSSED, SHAKEN, ROCKED, DROPPED, SPUN, UPSIDE_DOWN, EVENT_COUNT };

inline const char* name(Event e) {
  static const char* n[] = {"none", "sleep", "woken", "tossed", "shaken", "rocked", "dropped", "spun", "upside_down"};
  return e < EVENT_COUNT ? n[e] : "none";
}

struct Vec {
  float x = 0, y = 0, z = 0;
  float len() const { return std::sqrt(x * x + y * y + z * z); }
  Vec operator-(const Vec& o) const { return {x - o.x, y - o.y, z - o.z}; }
  float dot(const Vec& o) const { return x * o.x + y * o.y + z * o.z; }
};

struct Config {
  // thresholds are starting values to tune by log and by ear (see the design doc), not measured constants
  uint32_t sleep_hold_ms = 3000;        // lying down and still this long -> SLEEP
  uint32_t wake_hold_ms = 600;          // upright this long after sleeping -> WOKEN
  uint32_t upside_hold_ms = 600;        // inverted this long -> UPSIDE_DOWN (once per episode)
  float down_dot = 0.35f;               // dot(gravity, upright) below this = lying down (> ~70 deg from upright)
  float up_dot = 0.70f;                 // above this = upright
  float inverted_dot = -0.70f;
  float inverted_release = -0.50f;      // hysteresis: a toy wobbling around -0.7 must not re-fire
  float still_mag_tol = 0.08f;          // |accel| within 1 g +- this ...
  float still_gyro_dps = 20.f;          // ... and gyro below this = "still" (a carried toy is not)
  uint32_t freefall_ms = 80;            // |accel| < freefall_g this long = airborne
  float freefall_g = 0.3f;
  float land_g = 2.0f;                  // landing spike
  uint32_t land_window_ms = 500;
  uint32_t soft_catch_ff_ms = 180;      // improvement over the doc: a long flight caught softly still counts
  float soft_catch_g = 1.5f;
  float drop_g = 2.0f;                  // isolated spike with no flight before it
  uint32_t drop_settle_ms = 500;
  float tip_bump_g = 1.4f;              // upright -> lying within tip_window_ms with a bump this big = tipped over
  uint32_t tip_window_ms = 1500;
  uint32_t shake_window_ms = 1000;
  int shake_reversals = 4;
  float shake_hp_g = 0.35f;             // hysteresis for counting a reversal on the high-passed accel
  float shake_peak_g = 1.5f;
  float spin_dps = 300.f;
  uint32_t spin_hold_ms = 500;
  uint32_t rock_hold_ms = 4000;
  float rock_min_pp_g = 0.08f, rock_max_pp_g = 0.9f;   // peak-to-peak sway acceleration
  float rock_min_period_s = 0.8f, rock_max_period_s = 2.0f;
  float rock_gyro_max_dps = 150.f;
  uint32_t cooldown_ms[EVENT_COUNT] = {0, 0, 0, 10000, 8000, 30000, 5000, 8000, 8000};
};

class Detector {
 public:
  explicit Detector(const Config& c = Config()) : c_(c) {}

  void setUpright(const Vec& g) {
    float l = g.len();
    if (l < 0.5f) return;
    up_ = {g.x / l, g.y / l, g.z / l};
    calibrated_ = true;
  }
  Vec upright() const { return up_; }
  bool calibrated() const { return calibrated_; }
  bool asleep() const { return asleep_; }

  // Forget all motion state (after a new upright pose is learned or the toy is re-calibrated); keeps config and pose.
  void resetState() {
    bool cal = calibrated_; Vec up = up_;
    *this = Detector(c_);
    calibrated_ = cal; up_ = up;
  }

  // Calibration helper: call with each sample while the toy stands upright; returns true once it has 2 s of
  // still samples and has set the upright vector (so a toy that is being moved never calibrates wrongly).
  bool calibrate(uint32_t t, const Vec& a, const Vec& g) {
    bool still = std::fabs(a.len() - 1.f) < c_.still_mag_tol && g.len() < c_.still_gyro_dps;
    if (!still) { cal_n_ = 0; cal_sum_ = {}; cal_t0_ = 0; return false; }
    if (!cal_n_) cal_t0_ = t;
    cal_sum_.x += a.x; cal_sum_.y += a.y; cal_sum_.z += a.z;
    ++cal_n_;
    if (t - cal_t0_ >= 2000 && cal_n_ >= 20) {
      setUpright({cal_sum_.x / cal_n_, cal_sum_.y / cal_n_, cal_sum_.z / cal_n_});
      resetState();
      return true;
    }
    return false;
  }

  Event update(uint32_t t, const Vec& a, const Vec& g) {
    float dt = last_t_ ? (t - last_t_) / 1000.f : 0.02f;
    if (dt <= 0 || dt > 0.5f) dt = 0.02f;
    last_t_ = t;
    float mag = a.len(), gmag = g.len();

    // gravity estimates: fast (orientation) and slow (to high-pass the sway)
    if (!seeded_) { gf_ = gs_ = a; seeded_ = true; }
    float af = dt / (0.25f + dt), as = dt / (2.0f + dt);
    gf_ = {gf_.x + af * (a.x - gf_.x), gf_.y + af * (a.y - gf_.y), gf_.z + af * (a.z - gf_.z)};
    gs_ = {gs_.x + as * (a.x - gs_.x), gs_.y + as * (a.y - gs_.y), gs_.z + as * (a.z - gs_.z)};
    Vec hp = a - gs_;

    Event out = NONE;
    if (deferred_ != NONE) { out = deferred_; deferred_ = NONE; }   // a state change that lost the race last sample
    // returns true when the event was emitted (or deliberately cooled down), false when another event holds this sample
    auto fire = [&](Event e) -> bool {
      if (e == NONE) return true;
      if (e == SLEEP || e == WOKEN) {   // state changes are never dropped: hold them for the next sample
        if (out != NONE) { deferred_ = e; return true; }
        out = e;
        return true;
      }
      if (out != NONE) return false;
      if (fired_[e] && t - last_fire_[e] < c_.cooldown_ms[e]) return true;
      last_fire_[e] = t; fired_[e] = true;
      out = e;
      return true;
    };

    bool still = std::fabs(mag - 1.f) < c_.still_mag_tol && gmag < c_.still_gyro_dps;
    if (mag > 1.3f || still == false) last_motion_t_ = t;

    // ---- flight and landing: TOSSED (and, without flight, DROPPED) ----
    if (mag < c_.freefall_g) {
      if (!ff_) { ff_ = true; ff_t0_ = t; }
    } else if (ff_) {
      ff_ = false;
      ff_dur_ = t - ff_t0_;
      if (ff_dur_ >= c_.freefall_ms) { landing_ = true; landing_until_ = t + c_.land_window_ms; landing_peak_ = mag; tossed_t_ = t; tossed_ = true; }
    }
    if (landing_) {
      if (mag > landing_peak_) landing_peak_ = mag;
      bool hard = landing_peak_ >= c_.land_g;
      bool soft = ff_dur_ >= c_.soft_catch_ff_ms && landing_peak_ >= c_.soft_catch_g;
      if (hard || soft) { if (fire(TOSSED)) { landing_ = false; suppress_ = true; suppress_until_ = t + 1500; } }
      else if (reached(t, landing_until_)) landing_ = false;
    }

    // ---- recent spikes (for DROPPED vs shaking) ----
    if (mag > 1.3f) { last_spike_t_ = t; }
    if (mag >= c_.drop_g && !ff_ && !landing_ && !suppressed(t) && !pending_drop_ && (!tossed_ || t - tossed_t_ > 1500)) {
      if (!big_spike_ || t - prev_big_spike_t_ > 800) { pending_drop_ = true; drop_t0_ = t; drop_extra_ = false; }
      prev_big_spike_t_ = t; big_spike_ = true;
    } else if (mag >= c_.drop_g) {
      prev_big_spike_t_ = t; big_spike_ = true;
    }
    if (pending_drop_) {
      if (t - drop_t0_ > 60 && mag > 1.5f) drop_extra_ = true;           // more bumps: that is shaking, not one drop
      if (t - drop_t0_ >= c_.drop_settle_ms) {
        pending_drop_ = false;
        if (!drop_extra_ && !suppressed(t)) fire(DROPPED);
      }
    }

    // ---- orientation (only from samples that are not violent accelerations) ----
    bool valid = std::fabs(mag - 1.f) < 0.25f && gmag < 90.f;
    float d = 0;
    if (calibrated_ && valid) {
      float gl = gf_.len();
      if (gl > 0.3f) d = (gf_.x * up_.x + gf_.y * up_.y + gf_.z * up_.z) / gl;
      cur_d_ = d;
      orient_valid_ = true;
    } else {
      orient_valid_ = false;
    }

    if (calibrated_) {
      bool upright = orient_valid_ && cur_d_ > c_.up_dot;
      bool down = orient_valid_ && cur_d_ < c_.down_dot;
      bool inverted = orient_valid_ && cur_d_ < c_.inverted_dot;

      if (upright) { upright_since_ = upright_since_ ? upright_since_ : t; last_upright_t_ = t; up_bump_ = 0; }
      else if (orient_valid_ || t - last_upright_t_ > 400) upright_since_ = 0;

      // tipped over: left upright to lying within a moment, with a bump on the way
      if (last_upright_t_) { if (mag > up_bump_ && t - last_upright_t_ < c_.tip_window_ms) up_bump_ = mag; }
      if (down && !was_down_ && last_upright_t_ && t - last_upright_t_ < c_.tip_window_ms && up_bump_ >= c_.tip_bump_g &&
          !suppressed(t) && !asleep_) {
        fire(DROPPED);
      }
      was_down_ = down;

      // upside down: once per episode, at the hold time
      if (inverted && !asleep_) {
        if (!inv_since_) inv_since_ = t;
        if (!inv_fired_ && t - inv_since_ >= c_.upside_hold_ms) { inv_fired_ = true; fire(UPSIDE_DOWN); }
      } else if (orient_valid_ && cur_d_ > c_.inverted_release) { inv_since_ = 0; inv_fired_ = false; }

      // sleep: lying down (any way) and *still*, held. Carrying a toy sideways is not sleeping.
      bool lying_still = down && still;
      if (lying_still) {
        if (!down_since_) down_since_ = t;
      } else if (t - last_down_ok_ > 150) {
        down_since_ = 0;
      }
      if (lying_still) last_down_ok_ = t;
      if (!asleep_ && down_since_ && t - down_since_ >= c_.sleep_hold_ms) { asleep_ = true; woke_since_ = 0; fire(SLEEP); }

      if (asleep_) {
        if (upright) {
          if (!woke_since_) woke_since_ = t;
          if (t - woke_since_ >= c_.wake_hold_ms) { asleep_ = false; down_since_ = 0; woke_since_ = 0; fire(WOKEN); }
        } else if (orient_valid_ || t - last_upright_t_ > 400) woke_since_ = 0;
      }
    }

    // ---- shaken: direction reversals of the high-passed accel on any axis ----
    {
      const float* h[3] = {&hp.x, &hp.y, &hp.z};
      for (int i = 0; i < 3; ++i) {
        float v = *h[i];
        int s = v > c_.shake_hp_g ? 1 : (v < -c_.shake_hp_g ? -1 : 0);
        if (s && s != sh_sign_[i]) {
          if (sh_sign_[i]) { sh_ring_[i][sh_n_[i] % 16] = t; ++sh_n_[i]; }
          sh_sign_[i] = s;
        }
      }
      if (mag > sh_peak_) sh_peak_ = mag;
      if (t - sh_peak_t_ > c_.shake_window_ms) { sh_peak_ = mag; sh_peak_t_ = t; }
      for (int i = 0; i < 3; ++i) {
        int cnt = 0;
        for (int k = 0; k < 16 && k < sh_n_[i]; ++k) if (t - sh_ring_[i][k] <= c_.shake_window_ms) ++cnt;
        if (cnt >= c_.shake_reversals && sh_peak_ >= c_.shake_peak_g && !suppressed(t)) {
          for (int j = 0; j < 3; ++j) sh_n_[j] = 0;
          sh_peak_ = 0;
          pending_drop_ = false;
          fire(SHAKEN);
          break;
        }
      }
    }

    // ---- spun ----
    if (gmag > c_.spin_dps) {
      if (!spin_since_) spin_since_ = t;
      if (t - spin_since_ >= c_.spin_hold_ms && !suppressed(t)) { spin_since_ = 0; fire(SPUN); }
    } else {
      spin_since_ = 0;
    }

    // ---- rocked: regular gentle sway at 0.5-1.25 Hz for several seconds ----
    {
      // principal-axis sway: track the axis with the most high-passed energy via an envelope per axis
      float e[3] = {hp.x * hp.x, hp.y * hp.y, hp.z * hp.z};
      for (int i = 0; i < 3; ++i) rk_e_[i] += (e[i] - rk_e_[i]) * (dt / (1.0f + dt));
      int ax = 0;
      for (int i = 1; i < 3; ++i) if (rk_e_[i] > rk_e_[ax]) ax = i;
      float v = (&hp.x)[ax];
      rk_lp_ += (v - rk_lp_) * (dt / (0.12f + dt));   // smooth out vibration, keep ~1 Hz sway
      // peak-to-peak and period from successive upward zero crossings
      if (rk_lp_ > rk_pk_hi_) rk_pk_hi_ = rk_lp_;
      if (rk_lp_ < rk_pk_lo_) rk_pk_lo_ = rk_lp_;
      int s = rk_lp_ > 0.01f ? 1 : (rk_lp_ < -0.01f ? -1 : rk_sign_);
      if (s == 1 && rk_sign_ == -1) {
        float period = rk_last_up_ ? (t - rk_last_up_) / 1000.f : 0.f;
        float pp = rk_pk_hi_ - rk_pk_lo_;
        bool ok = period >= c_.rock_min_period_s && period <= c_.rock_max_period_s && pp >= c_.rock_min_pp_g &&
                  pp <= c_.rock_max_pp_g && gmag < c_.rock_gyro_max_dps && mag < 1.6f && !asleep_;
        if (ok) { if (!rk_start_) rk_start_ = rk_last_up_; rk_good_t_ = t; }
        else if (t - rk_good_t_ > 2500) rk_start_ = 0;
        rk_last_up_ = t;
        rk_pk_hi_ = -1e9f; rk_pk_lo_ = 1e9f;
        if (rk_start_ && t - rk_start_ >= c_.rock_hold_ms && !suppressed(t)) { rk_start_ = 0; fire(ROCKED); }
      }
      rk_sign_ = s;
      if (rk_start_ && t - rk_good_t_ > 3000) rk_start_ = 0;
    }
    return out;
  }

 private:
  bool suppressed(uint32_t t) const { return suppress_ && !reached(t, suppress_until_); }
  Config c_;
  Event deferred_ = NONE;
  bool fired_[EVENT_COUNT] = {false};
  bool landing_ = false, tossed_ = false, suppress_ = false, big_spike_ = false;
  Vec up_{0, 0, 1}, gf_, gs_, cal_sum_;
  bool calibrated_ = false, seeded_ = false, asleep_ = false, orient_valid_ = false, was_down_ = false;
  uint32_t last_t_ = 0, last_fire_[EVENT_COUNT] = {0}, last_motion_t_ = 0, last_spike_t_ = 0;
  uint32_t cal_n_ = 0, cal_t0_ = 0;
  // flight/landing
  bool ff_ = false;
  uint32_t ff_t0_ = 0, ff_dur_ = 0, landing_until_ = 0, tossed_t_ = 0, suppress_until_ = 0;
  float landing_peak_ = 0;
  // drop
  bool pending_drop_ = false, drop_extra_ = false;
  uint32_t drop_t0_ = 0, prev_big_spike_t_ = 0;
  // orientation
  float cur_d_ = 1;
  uint32_t upright_since_ = 0, last_upright_t_ = 0, down_since_ = 0, last_down_ok_ = 0, woke_since_ = 0, inv_since_ = 0;
  float up_bump_ = 0;
  bool inv_fired_ = false;
  // shake
  int sh_sign_[3] = {0, 0, 0};
  uint32_t sh_ring_[3][16] = {{0}};
  int sh_n_[3] = {0, 0, 0};
  float sh_peak_ = 0;
  uint32_t sh_peak_t_ = 0;
  // spin
  uint32_t spin_since_ = 0;
  // rock
  float rk_e_[3] = {0, 0, 0}, rk_lp_ = 0, rk_pk_hi_ = -1e9f, rk_pk_lo_ = 1e9f;
  int rk_sign_ = 0;
  uint32_t rk_last_up_ = 0, rk_start_ = 0, rk_good_t_ = 0;
};

}  // namespace imu
