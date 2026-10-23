#include "ppf_r361s.h"
#include "esphome/core/log.h"
#include "esphome/core/hal.h"

#if defined(USE_ESP_IDF)
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "esp_system.h"
#endif

namespace esphome {
namespace ppf_r361s {

static const char *const TAG = "ppf_r361s";

void PPFR361SComponent::setup() {
  ESP_LOGCONFIG(TAG, "Setting up Pawsync PPF-R361S Dual-MCU UART Bridge...");
  this->rx_buffer_.reserve(256);

  // Load persistent schedules from NVS
  this->load_schedule_from_nvs_();

  // Indicate solid connected Wi-Fi state to coprocessor front LED
  this->set_wifi_led(2);

  // Push active schedule to coprocessor EEPROM for autonomous offline execution
  this->sync_schedules_to_coprocessor();

  // Request initial status report from coprocessor
  this->poll_status_();
}

void PPFR361SComponent::loop() {
  // Read available bytes from UART buffer
  while (this->available()) {
    uint8_t byte;
    this->read_byte(&byte);
    this->rx_buffer_.push_back(byte);
  }

  if (!this->rx_buffer_.empty()) {
    this->parse_rx_buffer_();
  }

  // Periodic heartbeat / telemetry poll
  uint32_t now_ms = millis();
  if (now_ms - this->last_poll_time_ >= this->poll_interval_ms_) {
    this->last_poll_time_ = now_ms;
    this->poll_status_();
  }

  // Calibration Settling State Handler (measures settled kibble weight after 3s)
  if (this->calib_state_ == CALIB_SETTLING) {
    if (now_ms - this->calib_timer_ >= 3000) {
      this->calib_state_ = CALIB_IDLE;
      float weight = (this->bowl_weight_sensor_ != nullptr) ? this->bowl_weight_sensor_->state : 0.0f;
      if (!std::isnan(weight) && weight > 2.0f && this->calib_portions_ > 0) {
        float calculated_g = weight / static_cast<float>(this->calib_portions_);
        ESP_LOGI(TAG, "Portion calibration SUCCESS! Total %.1fg / %d portions = %.2fg/portion",
                 weight, this->calib_portions_, calculated_g);
        this->set_grams_per_portion(calculated_g);
        if (this->grams_per_portion_number_ != nullptr)
          this->grams_per_portion_number_->publish_state(calculated_g);

        char buf[64];
        snprintf(buf, sizeof(buf), "Calibrated: %.1fg/portion", calculated_g);
        if (this->status_text_sensor_ != nullptr)
          this->status_text_sensor_->publish_state(buf);
      } else {
        ESP_LOGW(TAG, "Calibration FAILED: No weight detected in bowl after dispensing (weight=%.1fg)", weight);
        if (this->status_text_sensor_ != nullptr)
          this->status_text_sensor_->publish_state("Calibration Failed: Hopper empty?");
      }
    }
  }

  // Minute schedule tick
  if (this->time_ != nullptr) {
    ESPTime now = this->time_->now();
    if (now.is_valid()) {
      if (now.minute != this->last_scheduled_minute_) {
        this->last_scheduled_minute_ = now.minute;
        this->evaluate_schedules_(now);
      }
    }
  }
}

void PPFR361SComponent::dump_config() {
  ESP_LOGCONFIG(TAG, "Pawsync PPF-R361S Feeder:");
  LOG_SENSOR("  ", "Bowl Weight", this->bowl_weight_sensor_);
  LOG_SENSOR("  ", "Battery Level", this->battery_level_sensor_);
  LOG_SENSOR("  ", "Last Feed Weight", this->last_feed_weight_sensor_);
  LOG_SENSOR("  ", "Portions Dispensed Today", this->portions_today_sensor_);
  LOG_BINARY_SENSOR("  ", "Power Adapter (AC)", this->power_adapter_sensor_);
  LOG_BINARY_SENSOR("  ", "Food Hopper Low", this->food_low_sensor_);
  LOG_BINARY_SENSOR("  ", "Motor Jammed", this->motor_jammed_sensor_);
  LOG_BINARY_SENSOR("  ", "Bowl Connected", this->bowl_connected_sensor_);
  LOG_TEXT_SENSOR("  ", "Feeder Status", this->status_text_sensor_);
  LOG_TEXT_SENSOR("  ", "Next Scheduled Meal", this->next_meal_sensor_);
  LOG_TEXT_SENSOR("  ", "Schedule Summary", this->schedule_summary_sensor_);
  LOG_SWITCH("  ", "Child Lock", this->child_lock_switch_);
  LOG_SWITCH("  ", "Slow Feed", this->slow_feed_switch_);
  LOG_SWITCH("  ", "Sleep Mode", this->sleep_mode_switch_);
  LOG_SWITCH("  ", "Intelligent Feeding", this->intelligent_feeding_switch_);
  LOG_NUMBER("  ", "Manual Feed Portions", this->manual_feed_portions_number_);

  ESP_LOGCONFIG(TAG, "  On-Device Schedule: Active Plan %u, Portion Density: %.1fg/portion, Intelligent: %s",
                this->storage_.active_plan_idx + 1,
                this->storage_.grams_per_portion,
                this->storage_.intelligent_feeding ? "YES" : "NO");
}

uint8_t PPFR361SComponent::calculate_checksum_(const uint8_t *buf, size_t len) {
  uint32_t sum = 0;
  for (size_t i = 0; i < len; i++) {
    if (i == 5) continue; // Byte 5 is checksum placeholder
    sum += buf[i];
  }
  return static_cast<uint8_t>((~sum) & 0xFF);
}

void PPFR361SComponent::send_frame_(uint8_t frame_type, uint8_t sub_cmd, uint16_t opcode,
                                   uint8_t status, const std::vector<std::pair<uint8_t, std::vector<uint8_t>>> &klv_items) {
  // Encode inner KLV payload
  std::vector<uint8_t> inner;
  inner.push_back(sub_cmd);
  inner.push_back(static_cast<uint8_t>(opcode & 0xFF));
  inner.push_back(static_cast<uint8_t>((opcode >> 8) & 0xFF));
  inner.push_back(status);

  for (const auto &item : klv_items) {
    inner.push_back(item.first); // Key ID
    uint16_t val_len = static_cast<uint16_t>(item.second.size());
    inner.push_back(static_cast<uint8_t>(val_len & 0xFF));
    inner.push_back(static_cast<uint8_t>((val_len >> 8) & 0xFF));
    inner.insert(inner.end(), item.second.begin(), item.second.end());
  }

  uint16_t payload_len = static_cast<uint16_t>(inner.size());
  std::vector<uint8_t> frame;
  frame.reserve(payload_len + 6);
  frame.push_back(FRAME_HEADER);
  frame.push_back(frame_type);
  frame.push_back(this->tx_seq_++);
  frame.push_back(static_cast<uint8_t>(payload_len & 0xFF));
  frame.push_back(static_cast<uint8_t>((payload_len >> 8) & 0xFF));
  frame.push_back(0x00); // Checksum byte at index 5
  frame.insert(frame.end(), inner.begin(), inner.end());

  frame[5] = this->calculate_checksum_(frame.data(), frame.size());

  ESP_LOGV(TAG, "UART TX: Opcode 0x%04X, Seq %d, Len %d", opcode, frame[2], (int)frame.size());
  this->write_array(frame.data(), frame.size());
}

void PPFR361SComponent::parse_rx_buffer_() {
  while (!this->rx_buffer_.empty()) {
    // Find header sync byte 0xA5
    if (this->rx_buffer_[0] != FRAME_HEADER) {
      this->rx_buffer_.erase(this->rx_buffer_.begin());
      continue;
    }

    if (this->rx_buffer_.size() < 6) {
      // Need at least header to read payload length
      return;
    }

    uint16_t payload_len = this->rx_buffer_[3] | (static_cast<uint16_t>(this->rx_buffer_[4]) << 8);
    size_t full_frame_len = payload_len + 6;

    if (this->rx_buffer_.size() < full_frame_len) {
      // Waiting for complete frame to arrive
      return;
    }

    // Verify frame checksum: sum of all bytes modulo 256 must be 0xFF
    uint32_t sum = 0;
    for (size_t i = 0; i < full_frame_len; i++) {
      sum += this->rx_buffer_[i];
    }

    if ((sum & 0xFF) == 0xFF) {
      this->process_frame_(this->rx_buffer_.data(), full_frame_len);
      this->rx_buffer_.erase(this->rx_buffer_.begin(), this->rx_buffer_.begin() + full_frame_len);
    } else {
      ESP_LOGW(TAG, "Frame checksum error (modulo 256 sum: 0x%02X != 0xFF), dropping sync byte", (unsigned int)(sum & 0xFF));
      this->rx_buffer_.erase(this->rx_buffer_.begin());
    }
  }
}

bool PPFR361SComponent::process_frame_(const uint8_t *frame, size_t len) {
  if (len < 10) return false;

  uint8_t sub_cmd = frame[6];
  uint16_t opcode = frame[7] | (static_cast<uint16_t>(frame[8]) << 8);
  uint8_t status = frame[9];

  // Parse KLV elements from frame[10] to frame[len-1]
  std::map<uint8_t, std::vector<uint8_t>> klv_map;
  size_t idx = 10;
  while (idx + 3 <= len) {
    uint8_t key_id = frame[idx];
    uint16_t item_len = frame[idx + 1] | (static_cast<uint16_t>(frame[idx + 2]) << 8);
    idx += 3;
    if (idx + item_len > len) break;
    std::vector<uint8_t> val(frame + idx, frame + idx + item_len);
    klv_map[key_id] = val;
    idx += item_len;
  }

  ESP_LOGD(TAG, "UART RX: Opcode 0x%04X, Status %d, KLV count %d", opcode, status, (int)klv_map.size());
  this->handle_opcode_(opcode, status, klv_map);
  return true;
}

void PPFR361SComponent::handle_opcode_(uint16_t opcode, uint8_t status,
                                      const std::map<uint8_t, std::vector<uint8_t>> &klv) {
  switch (opcode) {
    case OPCODE_STATUS_REPORT: { // 0x5593 - Full Telemetry Status Report
      // Key 3: child_lock (0 = Unlocked, 1 = Locked)
      if (klv.count(3) && !klv.at(3).empty()) {
        bool locked = (klv.at(3)[0] != 0);
        if (this->child_lock_switch_ != nullptr)
          this->child_lock_switch_->publish_state(locked);
      }

      // Key 4: food_remind (Food Hopper Low)
      if (klv.count(4) && !klv.at(4).empty()) {
        bool food_low = (klv.at(4)[0] != 0);
        if (this->food_low_sensor_ != nullptr)
          this->food_low_sensor_->publish_state(food_low);
      }

      // Key 5: battery_percent (0-100%)
      if (klv.count(5) && !klv.at(5).empty()) {
        float battery = static_cast<float>(klv.at(5)[0]);
        if (this->battery_level_sensor_ != nullptr)
          this->battery_level_sensor_->publish_state(battery);
      }

      // Key 7: powerAdapter (0 = Battery, 1 = AC Adapter)
      if (klv.count(7) && !klv.at(7).empty()) {
        bool ac_power = (klv.at(7)[0] != 0);
        if (this->power_adapter_sensor_ != nullptr)
          this->power_adapter_sensor_->publish_state(ac_power);

        // Power source transition handling
        if (this->ac_power_ != ac_power) {
          this->ac_power_ = ac_power;
          if (!ac_power) {
            ESP_LOGW(TAG, "DC power unplugged: Entering Battery Power-Save Mode (throttling poll to 2min, LEDs off)");
            this->poll_interval_ms_ = 120000;
            this->set_wifi_led(0);
          } else {
            ESP_LOGI(TAG, "DC power restored: Restoring normal operational profile");
            this->poll_interval_ms_ = 30000;
            this->set_wifi_led(2);
            this->sync_clock();
          }
        }
      }

      // Key 8: bowlWeight (grams, int16 LE)
      if (klv.count(8) && klv.at(8).size() >= 2) {
        int16_t weight = static_cast<int16_t>(klv.at(8)[0] | (klv.at(8)[1] << 8));
        if (this->bowl_weight_sensor_ != nullptr)
          this->bowl_weight_sensor_->publish_state(static_cast<float>(weight));
        if (this->bowl_connected_sensor_ != nullptr)
          this->bowl_connected_sensor_->publish_state(true);
      }

      if (this->status_text_sensor_ != nullptr && this->calib_state_ == CALIB_IDLE)
        this->status_text_sensor_->publish_state("Online / Standby");
      break;
    }

    case OPCODE_DISPENSE_RESULT: { // 0x5596 - Dispense Complete Telemetry
      uint8_t portions = 0;
      uint8_t code = 0;

      if (klv.count(2) && !klv.at(2).empty())
        portions = klv.at(2)[0];
      if (klv.count(3) && !klv.at(3).empty())
        code = klv.at(3)[0];

      ESP_LOGI(TAG, "Feed result: portions=%d, code=%d", portions, code);

      // Handle Portion Calibration State Machine
      if (this->calib_state_ == CALIB_DISPENSING) {
        if (code == 0) {
          ESP_LOGI(TAG, "Calibration test dispense finished (%d portions). Waiting 3s for load cell settling...", portions);
          this->calib_state_ = CALIB_SETTLING;
          this->calib_timer_ = millis();
          if (this->status_text_sensor_ != nullptr)
            this->status_text_sensor_->publish_state("Calibrating: Settling & weighing...");
        } else {
          ESP_LOGE(TAG, "Calibration failed: Motor jam or chute error during test dispense!");
          this->calib_state_ = CALIB_IDLE;
          if (this->status_text_sensor_ != nullptr)
            this->status_text_sensor_->publish_state("Calibration Failed: Jam/Chute error");
        }
      }

      if (code == 0) {
        this->portions_today_ += portions;
        if (this->portions_today_sensor_ != nullptr)
          this->portions_today_sensor_->publish_state(this->portions_today_);
        if (this->motor_jammed_sensor_ != nullptr)
          this->motor_jammed_sensor_->publish_state(false);
        if (this->status_text_sensor_ != nullptr && this->calib_state_ == CALIB_IDLE)
          this->status_text_sensor_->publish_state("Feeding Complete");
      } else if (code == 1) {
        ESP_LOGE(TAG, "FEED ERROR: Motor Jammed!");
        if (this->motor_jammed_sensor_ != nullptr)
          this->motor_jammed_sensor_->publish_state(true);
        if (this->status_text_sensor_ != nullptr)
          this->status_text_sensor_->publish_state("Motor Jammed");
      } else if (code == 2) {
        ESP_LOGW(TAG, "FEED WARNING: Chute Blocked!");
        if (this->status_text_sensor_ != nullptr)
          this->status_text_sensor_->publish_state("Outlet Blocked");
      }
      break;
    }

    case OPCODE_TARE_BOWL: { // 0x55A3 - Tare ACK
      if (klv.count(1) && !klv.at(1).empty()) {
        uint8_t result = klv.at(1)[0];
        if (result == 0) {
          ESP_LOGI(TAG, "Bowl scale tare successful (0g confirmed)");
          if (this->bowl_weight_sensor_ != nullptr)
            this->bowl_weight_sensor_->publish_state(0.0f);
          if (this->bowl_connected_sensor_ != nullptr)
            this->bowl_connected_sensor_->publish_state(true);

          if (this->calib_state_ == CALIB_TARING) {
            ESP_LOGI(TAG, "Calibration tare confirmed 0g. Dispensing %d test portions...", this->calib_portions_);
            if (this->status_text_sensor_ != nullptr)
              this->status_text_sensor_->publish_state("Calibrating: Dispensing test portions...");
            this->calib_state_ = CALIB_DISPENSING;
            this->calib_timer_ = millis();
            this->feed(this->calib_portions_, false); // Dispense silently
          } else {
            if (this->status_text_sensor_ != nullptr)
              this->status_text_sensor_->publish_state("Scale Tared");
          }
        } else if (result == 1) {
          ESP_LOGW(TAG, "Tare failed: Weight Fluctuating / Unstable");
          if (this->calib_state_ == CALIB_TARING) this->calib_state_ = CALIB_IDLE;
          if (this->status_text_sensor_ != nullptr)
            this->status_text_sensor_->publish_state("Tare Failed: Unstable Weight");
        } else if (result == 2) {
          ESP_LOGW(TAG, "Tare failed: Bowl Disconnected / Off Scale");
          if (this->calib_state_ == CALIB_TARING) this->calib_state_ = CALIB_IDLE;
          if (this->bowl_connected_sensor_ != nullptr)
            this->bowl_connected_sensor_->publish_state(false);
          if (this->status_text_sensor_ != nullptr)
            this->status_text_sensor_->publish_state("Bowl Disconnected");
        } else {
          ESP_LOGW(TAG, "Bowl scale tare failed (result code %d)", result);
          if (this->calib_state_ == CALIB_TARING) this->calib_state_ = CALIB_IDLE;
          if (this->status_text_sensor_ != nullptr)
            this->status_text_sensor_->publish_state("Tare Failed");
        }
      }
      break;
    }

    case OPCODE_SCHEDULE_TRIGGER: { // 0x5598 - Offline Scheduled Meal Fired
      ESP_LOGI(TAG, "Autonomous scheduled meal fired by coprocessor!");
      if (this->status_text_sensor_ != nullptr)
        this->status_text_sensor_->publish_state("Scheduled Feed Running");
      this->schedule_trigger_callback_.call();
      break;
    }

    case OPCODE_BUTTON_EVENT: { // 0x5597 - Hardware Button Event
      if (klv.count(1) && !klv.at(1).empty()) {
        uint8_t btn = klv.at(1)[0];
        ESP_LOGI(TAG, "Hardware button event from MCU: 0x%02X", btn);
      }
      break;
    }

    default:
      ESP_LOGV(TAG, "Unhandled Opcode 0x%04X received", opcode);
      break;
  }
}

void PPFR361SComponent::poll_status_() {
  // Opcode 0x5590: Status Poll Query
  this->send_frame_(0x02, 0x05, OPCODE_STATUS_POLL, 0x00, {});
}

void PPFR361SComponent::feed(uint16_t portions, bool sound) {
  if (portions == 0) portions = 1;
  if (portions > 20) portions = 20;

  ESP_LOGI(TAG, "Dispensing %d portion(s)...", portions);
  if (this->status_text_sensor_ != nullptr && this->calib_state_ == CALIB_IDLE)
    this->status_text_sensor_->publish_state("Feeding...");

  std::vector<std::pair<uint8_t, std::vector<uint8_t>>> items;
  items.push_back({1, {1}}); // Key 1: Mode = 1 (portion)
  items.push_back({2, {static_cast<uint8_t>(portions & 0xFF), static_cast<uint8_t>((portions >> 8) & 0xFF)}});
  items.push_back({3, {0x3C, 0x00}}); // Key 3: Timeout = 60s
  items.push_back({4, {static_cast<uint8_t>(sound ? 1 : 0)}});

  this->send_frame_(0x02, 0x04, OPCODE_FEED_CMD, 0x00, items);
}

void PPFR361SComponent::tare_bowl() {
  ESP_LOGI(TAG, "Zeroing bowl scale...");
  this->send_frame_(0x02, 0x05, OPCODE_TARE_BOWL, 0x00, {});
}

void PPFR361SComponent::start_portion_calibration(uint16_t portions) {
  if (portions == 0) portions = 3;
  if (portions > 10) portions = 10;

  ESP_LOGI(TAG, "Starting Automated Kibble Portion Calibration wizard (%d portions)...", portions);
  this->calib_portions_ = portions;
  this->calib_state_ = CALIB_TARING;
  this->calib_timer_ = millis();

  if (this->status_text_sensor_ != nullptr)
    this->status_text_sensor_->publish_state("Calibrating: Taring bowl scale...");

  this->tare_bowl();
}

void PPFR361SComponent::set_child_lock(bool locked) {
  ESP_LOGI(TAG, "Setting child lock: %s", locked ? "ON" : "OFF");
  std::vector<std::pair<uint8_t, std::vector<uint8_t>>> items;
  items.push_back({1, {static_cast<uint8_t>(locked ? 1 : 0)}});
  this->send_frame_(0x02, 0x04, OPCODE_CHILD_LOCK, 0x00, items);
  if (this->child_lock_switch_ != nullptr)
    this->child_lock_switch_->publish_state(locked);
}

void PPFR361SComponent::set_slow_feed(bool slow) {
  ESP_LOGI(TAG, "Setting slow feed mode: %s", slow ? "ON" : "OFF");
  std::vector<std::pair<uint8_t, std::vector<uint8_t>>> items;
  items.push_back({1, {static_cast<uint8_t>(slow ? 1 : 0)}});
  this->send_frame_(0x02, 0x05, OPCODE_SLOW_FEED, 0x00, items);
  if (this->slow_feed_switch_ != nullptr)
    this->slow_feed_switch_->publish_state(slow);
}

void PPFR361SComponent::set_sleep_mode(bool sleep) {
  ESP_LOGI(TAG, "Setting night sleep mode: %s", sleep ? "ON" : "OFF");
  std::vector<std::pair<uint8_t, std::vector<uint8_t>>> items;
  items.push_back({1, {static_cast<uint8_t>(sleep ? 1 : 0)}});
  items.push_back({2, {0x00}});
  this->send_frame_(0x02, 0x04, OPCODE_SLEEP_MODE, 0x00, items);
  if (this->sleep_mode_switch_ != nullptr)
    this->sleep_mode_switch_->publish_state(sleep);
}

void PPFR361SComponent::set_wifi_led(uint8_t mode) {
  std::vector<std::pair<uint8_t, std::vector<uint8_t>>> items;
  items.push_back({1, {mode}});
  this->send_frame_(0x02, 0x14, OPCODE_WIFI_LED, 0x00, items);
}

void PPFR361SComponent::sync_clock(uint32_t epoch_sec) {
  if (epoch_sec == 0) {
    epoch_sec = static_cast<uint32_t>(::time(nullptr));
  }
  if (epoch_sec < 1700000000) {
    ESP_LOGW(TAG, "System time not yet valid (%u), skipping clock sync", (unsigned int)epoch_sec);
    return;
  }
  ESP_LOGI(TAG, "Syncing epoch clock (%u) to coprocessor...", (unsigned int)epoch_sec);
  std::vector<std::pair<uint8_t, std::vector<uint8_t>>> items;
  items.push_back({1, {
    static_cast<uint8_t>(epoch_sec & 0xFF),
    static_cast<uint8_t>((epoch_sec >> 8) & 0xFF),
    static_cast<uint8_t>((epoch_sec >> 16) & 0xFF),
    static_cast<uint8_t>((epoch_sec >> 24) & 0xFF)
  }});
  this->send_frame_(0x02, 0x14, OPCODE_CLOCK_SYNC, 0x00, items);

  // Auto-sync active schedule to coprocessor following clock sync
  this->sync_schedules_to_coprocessor();
}

// On-Device Schedule Engine (Matching Stock 7 Plans x 10 Meals Capability)

void PPFR361SComponent::load_schedule_from_nvs_() {
  ESPPreferenceObject pref = global_preferences->make_preference<ScheduleStorage>(fnv1_hash("ppf_r361s_sched"), true);
  if (!pref.load(&this->storage_) || this->storage_.magic != 0x50534348) {
    ESP_LOGI(TAG, "Initializing default schedule storage in NVS flash...");
    this->storage_ = ScheduleStorage{};
    this->storage_.magic = 0x50534348;
    this->storage_.active_plan_idx = 0;
    this->storage_.intelligent_feeding = false;
    this->storage_.grams_per_portion = 8.0f;

    // Initialize Plan 1: Default Daily Plan
    snprintf(this->storage_.plans[0].name, sizeof(this->storage_.plans[0].name), "Daily");
    this->storage_.plans[0].enabled = true;
    this->storage_.plans[0].repeat_days = 0x7F; // All days

    // Meal 1: Breakfast at 08:00 AM (2 portions)
    this->storage_.plans[0].meals[0].enabled = true;
    this->storage_.plans[0].meals[0].hour = 8;
    this->storage_.plans[0].meals[0].minute = 0;
    this->storage_.plans[0].meals[0].portions = 2;
    this->storage_.plans[0].meals[0].days = 0x7F;
    this->storage_.plans[0].meals[0].sound = true;

    // Meal 2: Dinner at 18:00 PM (3 portions)
    this->storage_.plans[0].meals[1].enabled = true;
    this->storage_.plans[0].meals[1].hour = 18;
    this->storage_.plans[0].meals[1].minute = 0;
    this->storage_.plans[0].meals[1].portions = 3;
    this->storage_.plans[0].meals[1].days = 0x7F;
    this->storage_.plans[0].meals[1].sound = true;

    this->save_schedule_to_nvs_();
  } else {
    ESP_LOGI(TAG, "Loaded schedule storage from NVS: Active Plan %u, Density %.1fg/portion",
             this->storage_.active_plan_idx + 1, this->storage_.grams_per_portion);
  }

  if (this->intelligent_feeding_switch_ != nullptr) {
    this->intelligent_feeding_switch_->publish_state(this->storage_.intelligent_feeding);
  }
  if (this->grams_per_portion_number_ != nullptr) {
    this->grams_per_portion_number_->publish_state(this->storage_.grams_per_portion);
  }
}

void PPFR361SComponent::save_schedule_to_nvs_() {
  ESPPreferenceObject pref = global_preferences->make_preference<ScheduleStorage>(fnv1_hash("ppf_r361s_sched"), true);
  pref.save(&this->storage_);
  global_preferences->sync();
  this->update_schedule_sensors_();
}

void PPFR361SComponent::set_active_plan(uint8_t plan_idx) {
  if (plan_idx >= MAX_PLANS) return;
  ESP_LOGI(TAG, "Switching active feeding plan to Plan %u", plan_idx + 1);
  this->storage_.active_plan_idx = plan_idx;
  this->save_schedule_to_nvs_();
  this->sync_schedules_to_coprocessor();
}

void PPFR361SComponent::set_meal_schedule(uint8_t plan_idx, uint8_t meal_idx, bool enabled,
                                         uint8_t hour, uint8_t minute, uint8_t portions, uint8_t days, bool sound) {
  if (plan_idx >= MAX_PLANS || meal_idx >= MAX_MEALS_PER_PLAN) return;
  if (hour > 23) hour = 23;
  if (minute > 59) minute = 59;
  if (portions == 0) portions = 1;
  if (portions > 20) portions = 20;

  ScheduleMeal &m = this->storage_.plans[plan_idx].meals[meal_idx];
  m.enabled = enabled;
  m.hour = hour;
  m.minute = minute;
  m.portions = portions;
  m.days = days;
  m.sound = sound;

  ESP_LOGI(TAG, "Configured Plan %u Meal %u: %s %02d:%02d (%d portions, days 0x%02X, sound %d)",
           plan_idx + 1, meal_idx + 1, enabled ? "ENABLED" : "DISABLED", hour, minute, portions, days, sound);
  this->save_schedule_to_nvs_();
  if (plan_idx == this->storage_.active_plan_idx) {
    this->sync_schedules_to_coprocessor();
  }
}

void PPFR361SComponent::sync_schedules_to_coprocessor() {
  uint8_t active_idx = this->storage_.active_plan_idx;
  if (active_idx >= MAX_PLANS) active_idx = 0;
  const auto &plan = this->storage_.plans[active_idx];

  std::vector<uint8_t> meals_payload;
  uint8_t count = 0;
  for (uint8_t i = 0; i < MAX_MEALS_PER_PLAN; i++) {
    if (plan.meals[i].enabled) {
      meals_payload.push_back(i); // meal_idx (0..9)
      meals_payload.push_back(1); // enabled
      meals_payload.push_back(plan.meals[i].hour);
      meals_payload.push_back(plan.meals[i].minute);
      meals_payload.push_back(static_cast<uint8_t>(plan.meals[i].portions & 0xFF));
      meals_payload.push_back(static_cast<uint8_t>((plan.meals[i].portions >> 8) & 0xFF));
      meals_payload.push_back(plan.meals[i].days);
      meals_payload.push_back(plan.meals[i].sound ? 1 : 0);
      count++;
    }
  }

  std::vector<std::pair<uint8_t, std::vector<uint8_t>>> items;
  items.push_back({1, {active_idx}});
  items.push_back({2, {count}});
  items.push_back({3, meals_payload});

  ESP_LOGI(TAG, "Syncing active plan %u (%u meal(s)) to coprocessor EEPROM via 0x55A6...", active_idx + 1, count);
  this->send_frame_(0x02, 0x14, OPCODE_PLAN_SYNC, 0x00, items);
}

void PPFR361SComponent::set_intelligent_feeding(bool enabled) {
  ESP_LOGI(TAG, "Setting Intelligent Feeding (Leftover Subtraction): %s", enabled ? "ON" : "OFF");
  this->storage_.intelligent_feeding = enabled;
  if (this->intelligent_feeding_switch_ != nullptr)
    this->intelligent_feeding_switch_->publish_state(enabled);
  this->save_schedule_to_nvs_();
}

void PPFR361SComponent::set_grams_per_portion(float grams) {
  if (grams > 0.0f) {
    this->storage_.grams_per_portion = grams;
    ESP_LOGI(TAG, "Saved kibble density to NVS: %.2fg/portion", grams);
    this->save_schedule_to_nvs_();
  }
}

void PPFR361SComponent::clear_plan(uint8_t plan_idx) {
  if (plan_idx >= MAX_PLANS) return;
  for (size_t m = 0; m < MAX_MEALS_PER_PLAN; m++) {
    this->storage_.plans[plan_idx].meals[m].enabled = false;
  }
  this->save_schedule_to_nvs_();
}

const ScheduleMeal &PPFR361SComponent::get_meal(uint8_t plan_idx, uint8_t meal_idx) const {
  if (plan_idx >= MAX_PLANS) plan_idx = 0;
  if (meal_idx >= MAX_MEALS_PER_PLAN) meal_idx = 0;
  return this->storage_.plans[plan_idx].meals[meal_idx];
}

void PPFR361SComponent::evaluate_schedules_(const ESPTime &now) {
  uint8_t today_mask = 1 << (now.day_of_week - 1);
  uint8_t plan_idx = this->storage_.active_plan_idx;
  if (plan_idx >= MAX_PLANS) plan_idx = 0;

  const auto &plan = this->storage_.plans[plan_idx];
  if (!plan.enabled || !(plan.repeat_days & today_mask)) {
    this->update_schedule_sensors_();
    return;
  }

  for (size_t m = 0; m < MAX_MEALS_PER_PLAN; m++) {
    const auto &meal = plan.meals[m];
    if (!meal.enabled) continue;
    if (!(meal.days & today_mask)) continue;

    if (now.hour == meal.hour && now.minute == meal.minute) {
      uint16_t portions_to_feed = meal.portions;

      // Intelligent Feeding leftover check
      if (this->storage_.intelligent_feeding && this->bowl_weight_sensor_ != nullptr) {
        float bowl_w = this->bowl_weight_sensor_->state;
        if (!std::isnan(bowl_w) && bowl_w > 0.0f) {
          float g_per_portion = this->storage_.grams_per_portion > 0 ? this->storage_.grams_per_portion : 8.0f;
          float target_weight = meal.portions * g_per_portion;
          if (bowl_w >= target_weight) {
            portions_to_feed = 0;
            ESP_LOGI(TAG, "Intelligent feed: Bowl has %.1fg (>= target %.1fg). Skipping meal %zu.",
                     bowl_w, target_weight, m + 1);
          } else {
            float needed = target_weight - bowl_w;
            portions_to_feed = static_cast<uint16_t>(std::ceil(needed / g_per_portion));
            if (portions_to_feed > meal.portions) portions_to_feed = meal.portions;
            ESP_LOGI(TAG, "Intelligent feed: Bowl has %.1fg. Adjusted meal %zu portions from %d to %d (target %.1fg)",
                     bowl_w, m + 1, meal.portions, portions_to_feed, target_weight);
          }
        }
      }

      if (portions_to_feed > 0) {
        ESP_LOGI(TAG, "Executing on-device scheduled meal %zu (Plan %u): %d portions", m + 1, plan_idx + 1, portions_to_feed);
        this->feed(portions_to_feed, meal.sound);
      }
    }
  }

  this->update_schedule_sensors_();
}

void PPFR361SComponent::update_schedule_sensors_() {
  if (this->time_ == nullptr) return;
  ESPTime now = this->time_->now();
  if (!now.is_valid()) return;

  uint8_t today_mask = 1 << (now.day_of_week - 1);
  uint8_t plan_idx = this->storage_.active_plan_idx;
  if (plan_idx >= MAX_PLANS) plan_idx = 0;
  const auto &plan = this->storage_.plans[plan_idx];

  int next_meal_idx = -1;
  int min_diff = 1440 * 2;
  int now_mins = now.hour * 60 + now.minute;

  std::string summary = "";

  for (size_t m = 0; m < MAX_MEALS_PER_PLAN; m++) {
    const auto &meal = plan.meals[m];
    if (!meal.enabled || !(meal.days & today_mask)) continue;

    int meal_mins = meal.hour * 60 + meal.minute;
    int diff = meal_mins - now_mins;
    if (diff > 0 && diff < min_diff) {
      min_diff = diff;
      next_meal_idx = m;
    }

    if (!summary.empty()) summary += " | ";
    char m_buf[32];
    snprintf(m_buf, sizeof(m_buf), "M%zu: %02d:%02d (%dp)", m + 1, meal.hour, meal.minute, meal.portions);
    summary += m_buf;
  }

  if (summary.empty()) {
    summary = "No active meals today";
  }

  if (this->schedule_summary_sensor_ != nullptr) {
    this->schedule_summary_sensor_->publish_state(summary);
  }

  if (this->next_meal_sensor_ != nullptr) {
    if (next_meal_idx >= 0) {
      char buf[32];
      snprintf(buf, sizeof(buf), "%02d:%02d (%d portions)",
               plan.meals[next_meal_idx].hour, plan.meals[next_meal_idx].minute, plan.meals[next_meal_idx].portions);
      this->next_meal_sensor_->publish_state(buf);
    } else {
      this->next_meal_sensor_->publish_state("Done for today");
    }
  }
}

void PPFR361SComponent::rollback_to_stock_firmware() {
  ESP_LOGW(TAG, "Initiating software rollback to stock firmware partition 'ota_1'...");
#if defined(USE_ESP_IDF)
  const esp_partition_t *ota1 = esp_partition_find_first(ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_APP_OTA_1, "ota_1");
  if (ota1 != nullptr) {
    esp_err_t err = esp_ota_set_boot_partition(ota1);
    if (err == ESP_OK) {
      ESP_LOGW(TAG, "Boot partition set to 'ota_1' successfully! Rebooting into stock factory firmware...");
      delay(100);
      esp_restart();
    } else {
      ESP_LOGE(TAG, "Failed to set boot partition to 'ota_1': 0x%x", err);
    }
  } else {
    ESP_LOGE(TAG, "Partition 'ota_1' not found in partition table!");
  }
#else
  ESP_LOGE(TAG, "Rollback to stock firmware is only supported under ESP-IDF framework.");
#endif
}

}  // namespace ppf_r361s
}  // namespace esphome
