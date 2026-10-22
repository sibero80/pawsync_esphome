#pragma once

#include "esphome/core/component.h"
#include "esphome/core/automation.h"
#include "esphome/core/helpers.h"
#include "esphome/core/time.h"
#include "esphome/core/preferences.h"
#include "esphome/components/uart/uart.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/binary_sensor/binary_sensor.h"
#include "esphome/components/switch/switch.h"
#include "esphome/components/button/button.h"
#include "esphome/components/number/number.h"
#include "esphome/components/text_sensor/text_sensor.h"
#include "esphome/components/time/real_time_clock.h"

#include <vector>
#include <map>
#include <ctime>
#include <cmath>
#include <cstring>

namespace esphome {
namespace ppf_r361s {

static const uint8_t FRAME_HEADER = 0xA5;

// Protocol Opcodes
static const uint16_t OPCODE_FEED_CMD           = 0x5018;
static const uint16_t OPCODE_CHILD_LOCK         = 0x5104;
static const uint16_t OPCODE_SLEEP_MODE         = 0x5105;
static const uint16_t OPCODE_SLOW_FEED          = 0x5107;
static const uint16_t OPCODE_WIFI_LED           = 0x5140;
static const uint16_t OPCODE_BUZZER_SWITCH      = 0x5141;
static const uint16_t OPCODE_STATUS_POLL        = 0x5590;
static const uint16_t OPCODE_INTELLIGENT_FEED   = 0x5592;
static const uint16_t OPCODE_STATUS_REPORT      = 0x5593;
static const uint16_t OPCODE_DISPENSE_PROGRESS  = 0x5594;
static const uint16_t OPCODE_SLEEP_CLOCK_SYNC   = 0x5595;
static const uint16_t OPCODE_DISPENSE_RESULT    = 0x5596;
static const uint16_t OPCODE_BUTTON_EVENT       = 0x5597;
static const uint16_t OPCODE_SCHEDULE_TRIGGER   = 0x5598;
static const uint16_t OPCODE_CLOCK_SYNC         = 0x55A1;
static const uint16_t OPCODE_TARE_BOWL          = 0x55A3;
static const uint16_t OPCODE_MOTOR_DIAGNOSTICS  = 0x55A4;
static const uint16_t OPCODE_SCALE_RAW_ADC      = 0x55A5;
static const uint16_t OPCODE_PLAN_SYNC          = 0x55A6;

// Schedule Storage Specifications (Matching Stock Capabilities)
static const size_t MAX_PLANS = 7;
static const size_t MAX_MEALS_PER_PLAN = 10;

enum PortionCalibrationState {
  CALIB_IDLE,
  CALIB_TARING,
  CALIB_DISPENSING,
  CALIB_SETTLING
};

struct ScheduleMeal {
  bool enabled{false};
  uint8_t hour{0};      // 0..23
  uint8_t minute{0};    // 0..59
  uint8_t portions{1};  // 1..20
  uint8_t days{0x7F};   // Bitmask: bit 0=Sun, 1=Mon, ..., 6=Sat (0x7F = Daily)
  bool sound{true};
};

struct FeedingPlan {
  char name[16]{"Plan"};
  uint8_t repeat_days{0x7F}; // Days this plan is active (bitmask)
  bool enabled{true};
  ScheduleMeal meals[MAX_MEALS_PER_PLAN];
};

struct ScheduleStorage {
  uint32_t magic{0x50534348}; // 'PSCH' (Pawsync Schedule)
  uint8_t active_plan_idx{0};  // 0..6
  bool intelligent_feeding{false};
  float grams_per_portion{8.0f};
  FeedingPlan plans[MAX_PLANS];
};

class PPFR361SComponent : public Component, public uart::UARTDevice {
 public:
  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::LATE; }

  // Entity setters - Sensors
  void set_bowl_weight_sensor(sensor::Sensor *s) { this->bowl_weight_sensor_ = s; }
  void set_battery_level_sensor(sensor::Sensor *s) { this->battery_level_sensor_ = s; }
  void set_last_feed_weight_sensor(sensor::Sensor *s) { this->last_feed_weight_sensor_ = s; }
  void set_portions_today_sensor(sensor::Sensor *s) { this->portions_today_sensor_ = s; }

  // Entity setters - Binary Sensors
  void set_power_adapter_sensor(binary_sensor::BinarySensor *s) { this->power_adapter_sensor_ = s; }
  void set_food_low_sensor(binary_sensor::BinarySensor *s) { this->food_low_sensor_ = s; }
  void set_motor_jammed_sensor(binary_sensor::BinarySensor *s) { this->motor_jammed_sensor_ = s; }
  void set_bowl_connected_sensor(binary_sensor::BinarySensor *s) { this->bowl_connected_sensor_ = s; }

  // Entity setters - Text Sensors
  void set_status_text_sensor(text_sensor::TextSensor *s) { this->status_text_sensor_ = s; }
  void set_next_meal_sensor(text_sensor::TextSensor *s) { this->next_meal_sensor_ = s; }
  void set_schedule_summary_sensor(text_sensor::TextSensor *s) { this->schedule_summary_sensor_ = s; }

  // Entity setters - Switches
  void set_child_lock_switch(switch_::Switch *s) { this->child_lock_switch_ = s; }
  void set_slow_feed_switch(switch_::Switch *s) { this->slow_feed_switch_ = s; }
  void set_sleep_mode_switch(switch_::Switch *s) { this->sleep_mode_switch_ = s; }
  void set_intelligent_feeding_switch(switch_::Switch *s) { this->intelligent_feeding_switch_ = s; }

  // Entity setters - Numbers
  void set_manual_feed_portions_number(number::Number *n) { this->manual_feed_portions_number_ = n; }
  void set_grams_per_portion_number(number::Number *n) { this->grams_per_portion_number_ = n; }

  // Time provider
  void set_time(time::RealTimeClock *time) { this->time_ = time; }

  // Public control APIs
  void feed(uint16_t portions, bool sound = true);
  void tare_bowl();
  void set_child_lock(bool locked);
  void set_slow_feed(bool slow);
  void set_sleep_mode(bool sleep);
  void set_wifi_led(uint8_t mode);
  void sync_clock(uint32_t epoch_sec = 0);

  // Automated Kibble Calibration Wizard
  void start_portion_calibration(uint16_t portions = 3);

  // Schedule Engine APIs (Up to 7 Plans, 10 Meals per Plan)
  void set_active_plan(uint8_t plan_idx);
  uint8_t get_active_plan() const { return this->storage_.active_plan_idx; }
  void set_meal_schedule(uint8_t plan_idx, uint8_t meal_idx, bool enabled, uint8_t hour, uint8_t minute,
                         uint8_t portions, uint8_t days, bool sound = true);
  void set_intelligent_feeding(bool enabled);
  bool get_intelligent_feeding() const { return this->storage_.intelligent_feeding; }
  void set_grams_per_portion(float grams);
  float get_grams_per_portion() const { return this->storage_.grams_per_portion; }
  void clear_plan(uint8_t plan_idx);
  const ScheduleMeal &get_meal(uint8_t plan_idx, uint8_t meal_idx) const;
  void sync_schedules_to_coprocessor();
  void add_on_schedule_trigger_callback(std::function<void()> callback) {
    this->schedule_trigger_callback_.add(std::move(callback));
  }

 protected:
  CallbackManager<void()> schedule_trigger_callback_{};

  // Serial frame handling
  void parse_rx_buffer_();
  bool process_frame_(const uint8_t *frame, size_t len);
  void handle_opcode_(uint16_t opcode, uint8_t status, const std::map<uint8_t, std::vector<uint8_t>> &klv);

  // Serial transmission
  void send_frame_(uint8_t frame_type, uint8_t sub_cmd, uint16_t opcode,
                   uint8_t status, const std::vector<std::pair<uint8_t, std::vector<uint8_t>>> &klv_items);

  uint8_t calculate_checksum_(const uint8_t *buf, size_t len);

  // Polling
  void poll_status_();

  // On-device Schedule Engine
  void load_schedule_from_nvs_();
  void save_schedule_to_nvs_();
  void evaluate_schedules_(const ESPTime &now);
  void update_schedule_sensors_();

  // Internal state
  std::vector<uint8_t> rx_buffer_;
  uint8_t tx_seq_{0};
  uint32_t last_poll_time_{0};
  uint32_t poll_interval_ms_{30000};
  bool ac_power_{true};
  uint32_t portions_today_{0};
  int last_scheduled_minute_{-1};

  // Calibration State Machine
  PortionCalibrationState calib_state_{CALIB_IDLE};
  uint32_t calib_timer_{0};
  uint16_t calib_portions_{3};

  // Schedule Storage in NVS
  ScheduleStorage storage_;

  // Time component
  time::RealTimeClock *time_{nullptr};

  // Entity pointers
  sensor::Sensor *bowl_weight_sensor_{nullptr};
  sensor::Sensor *battery_level_sensor_{nullptr};
  sensor::Sensor *last_feed_weight_sensor_{nullptr};
  sensor::Sensor *portions_today_sensor_{nullptr};

  binary_sensor::BinarySensor *power_adapter_sensor_{nullptr};
  binary_sensor::BinarySensor *food_low_sensor_{nullptr};
  binary_sensor::BinarySensor *motor_jammed_sensor_{nullptr};
  binary_sensor::BinarySensor *bowl_connected_sensor_{nullptr};

  text_sensor::TextSensor *status_text_sensor_{nullptr};
  text_sensor::TextSensor *next_meal_sensor_{nullptr};
  text_sensor::TextSensor *schedule_summary_sensor_{nullptr};

  switch_::Switch *child_lock_switch_{nullptr};
  switch_::Switch *slow_feed_switch_{nullptr};
  switch_::Switch *sleep_mode_switch_{nullptr};
  switch_::Switch *intelligent_feeding_switch_{nullptr};

  number::Number *manual_feed_portions_number_{nullptr};
  number::Number *grams_per_portion_number_{nullptr};
};

// Child switch classes
class PPFR361SChildLockSwitch : public switch_::Switch, public Parented<PPFR361SComponent> {
 protected:
  void write_state(bool state) override {
    this->parent_->set_child_lock(state);
  }
};

class PPFR361SSlowFeedSwitch : public switch_::Switch, public Parented<PPFR361SComponent> {
 protected:
  void write_state(bool state) override {
    this->parent_->set_slow_feed(state);
  }
};

class PPFR361SSleepModeSwitch : public switch_::Switch, public Parented<PPFR361SComponent> {
 protected:
  void write_state(bool state) override {
    this->parent_->set_sleep_mode(state);
  }
};

class PPFR361SIntelligentFeedingSwitch : public switch_::Switch, public Parented<PPFR361SComponent> {
 protected:
  void write_state(bool state) override {
    this->parent_->set_intelligent_feeding(state);
  }
};

// Child button classes
class PPFR361STareButton : public button::Button, public Parented<PPFR361SComponent> {
 protected:
  void press_action() override {
    this->parent_->tare_bowl();
  }
};

class PPFR361SFeedButton : public button::Button, public Parented<PPFR361SComponent> {
 public:
  void set_portions(uint16_t portions) { this->portions_ = portions; }
  void set_sound(bool sound) { this->sound_ = sound; }
 protected:
  void press_action() override {
    this->parent_->feed(this->portions_, this->sound_);
  }
  uint16_t portions_{1};
  bool sound_{true};
};

class PPFR361SCalibrateButton : public button::Button, public Parented<PPFR361SComponent> {
 protected:
  void press_action() override {
    this->parent_->start_portion_calibration(3);
  }
};

// Child number class
class PPFR361SManualPortionsNumber : public number::Number, public Parented<PPFR361SComponent> {
 protected:
  void control(float value) override {
    this->publish_state(value);
  }
};

// Action classes
template<typename... Ts> class PPFR361SFeedAction : public Action<Ts...>, public Parented<PPFR361SComponent> {
 public:
  TEMPLATABLE_VALUE(uint16_t, portions)
  TEMPLATABLE_VALUE(bool, sound)

  void play(const Ts &...x) override {
    uint16_t p = this->portions_.has_value() ? this->portions_.value(x...) : 1;
    bool s = this->sound_.has_value() ? this->sound_.value(x...) : true;
    this->parent_->feed(p, s);
  }
};

template<typename... Ts> class PPFR361STareAction : public Action<Ts...>, public Parented<PPFR361SComponent> {
 public:
  void play(const Ts &...x) override {
    this->parent_->tare_bowl();
  }
};

template<typename... Ts> class PPFR361SCalibratePortionAction : public Action<Ts...>, public Parented<PPFR361SComponent> {
 public:
  TEMPLATABLE_VALUE(uint16_t, portions)

  void play(const Ts &...x) override {
    uint16_t p = this->portions_.has_value() ? this->portions_.value(x...) : 3;
    this->parent_->start_portion_calibration(p);
  }
};

template<typename... Ts> class PPFR361SSyncClockAction : public Action<Ts...>, public Parented<PPFR361SComponent> {
 public:
  TEMPLATABLE_VALUE(uint32_t, epoch)

  void play(const Ts &...x) override {
    uint32_t ep = this->epoch_.has_value() ? this->epoch_.value(x...) : 0;
    this->parent_->sync_clock(ep);
  }
};

template<typename... Ts> class PPFR361SSetScheduleMealAction : public Action<Ts...>, public Parented<PPFR361SComponent> {
 public:
  TEMPLATABLE_VALUE(uint8_t, plan)
  TEMPLATABLE_VALUE(uint8_t, meal)
  TEMPLATABLE_VALUE(bool, enabled)
  TEMPLATABLE_VALUE(uint8_t, hour)
  TEMPLATABLE_VALUE(uint8_t, minute)
  TEMPLATABLE_VALUE(uint8_t, portions)
  TEMPLATABLE_VALUE(uint8_t, days)
  TEMPLATABLE_VALUE(bool, sound)

  void play(const Ts &...x) override {
    uint8_t p = this->plan_.has_value() ? this->plan_.value(x...) : 1;
    uint8_t m = this->meal_.has_value() ? this->meal_.value(x...) : 1;
    bool en = this->enabled_.has_value() ? this->enabled_.value(x...) : true;
    uint8_t h = this->hour_.has_value() ? this->hour_.value(x...) : 8;
    uint8_t min = this->minute_.has_value() ? this->minute_.value(x...) : 0;
    uint8_t port = this->portions_.has_value() ? this->portions_.value(x...) : 1;
    uint8_t d = this->days_.has_value() ? this->days_.value(x...) : 0x7F;
    bool s = this->sound_.has_value() ? this->sound_.value(x...) : true;

    // Convert 1-based indexing from user to 0-based internal indexing
    if (p > 0) p -= 1;
    if (m > 0) m -= 1;

    this->parent_->set_meal_schedule(p, m, en, h, min, port, d, s);
  }
};

template<typename... Ts> class PPFR361SSetActivePlanAction : public Action<Ts...>, public Parented<PPFR361SComponent> {
 public:
  TEMPLATABLE_VALUE(uint8_t, plan)

  void play(const Ts &...x) override {
    uint8_t p = this->plan_.has_value() ? this->plan_.value(x...) : 1;
    if (p > 0) p -= 1;
    this->parent_->set_active_plan(p);
  }
};

template<typename... Ts> class PPFR361SSyncSchedulesAction : public Action<Ts...>, public Parented<PPFR361SComponent> {
 public:
  void play(const Ts &...x) override {
    this->parent_->sync_schedules_to_coprocessor();
  }
};

class PPFR361SScheduleTrigger : public Trigger<> {
 public:
  explicit PPFR361SScheduleTrigger(PPFR361SComponent *parent) {
    parent->add_on_schedule_trigger_callback([this]() { this->trigger(); });
  }
};

}  // namespace ppf_r361s
}  // namespace esphome
