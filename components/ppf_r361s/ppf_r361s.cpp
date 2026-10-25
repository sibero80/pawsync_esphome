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
#if defined(USE_ESP_IDF)
  esp_ota_mark_app_valid_cancel_rollback();
#endif
  this->rx_buffer_.reserve(256);

  // Load persistent schedules from NVS
  this->load_schedule_from_nvs_();

  // Indicate solid connected Wi-Fi state to coprocessor front LED
  this->set_wifi_led(2);

  // Ensure coprocessor is unlocked on startup so remote & manual feed work out-of-the-box
  this->set_child_lock(false);

  // Push active schedule to coprocessor EEPROM for autonomous offline execution
  this->sync_schedules_to_coprocessor();

  // Request initial status report from coprocessor
  this->poll_status_();

  // Initialize baseline sensor states so Home Assistant entities are immediately populated
  if (this->battery_level_sensor_ != nullptr)
    this->battery_level_sensor_->publish_state(100.0f);
  if (this->bowl_weight_sensor_ != nullptr)
    this->bowl_weight_sensor_->publish_state(0.0f);
  if (this->power_adapter_sensor_ != nullptr)
    this->power_adapter_sensor_->publish_state(true);
  if (this->food_low_sensor_ != nullptr)
    this->food_low_sensor_->publish_state(false);
  if (this->motor_jammed_sensor_ != nullptr)
    this->motor_jammed_sensor_->publish_state(false);
  if (this->bowl_connected_sensor_ != nullptr)
    this->bowl_connected_sensor_->publish_state(true);
  if (this->portions_today_sensor_ != nullptr)
    this->portions_today_sensor_->publish_state(this->portions_today_);
  if (this->desiccant_days_sensor_ != nullptr)
    this->desiccant_days_sensor_->publish_state(30.0f);
  if (this->last_feed_weight_sensor_ != nullptr)
    this->last_feed_weight_sensor_->publish_state(0.0f);
  if (this->manual_feed_portions_number_ != nullptr)
    this->manual_feed_portions_number_->publish_state(1.0f);
  if (this->status_text_sensor_ != nullptr)
    this->status_text_sensor_->publish_state("Online / Standby");
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

  // Periodic heartbeat / telemetry poll (skip while dispensing to avoid interrupting motor cycle)
  uint32_t now_ms = millis();
  if (!this->is_dispensing_ && now_ms - this->last_poll_time_ >= this->poll_interval_ms_) {
    this->last_poll_time_ = now_ms;
    this->poll_status_();
  }

  // Hardware Watchdog / Safety Cutoff: only triggers if coprocessor motor fails to complete
  if (this->is_dispensing_) {
    uint32_t elapsed = now_ms - this->dispense_start_time_;

    if (elapsed > this->dispense_timeout_ms_) {
      ESP_LOGE(TAG, "EMERGENCY SAFETY CUTOFF: Dispense duration (%lu ms) exceeded timeout (%lu ms)! Forcing motor halt...",
               (unsigned long)elapsed, (unsigned long)this->dispense_timeout_ms_);
      this->is_dispensing_ = false;

      // 1. Send stop command with 0x22
      std::vector<std::pair<uint8_t, std::vector<uint8_t>>> stop_items;
      stop_items.push_back({1, {0x00, 0x00}});
      stop_items.push_back({2, {0x00, 0x00}});
      stop_items.push_back({3, {0x00}});
      this->send_frame_(0x22, OPCODE_FEED_CMD, 0x00, stop_items);

      if (this->restore_child_lock_after_feed_) {
        this->restore_child_lock_after_feed_ = false;
        this->send_frame_(0x22, OPCODE_CHILD_LOCK, 0x00, {{1, {0x01}}});
      }

      // 2. Set emergency interlock to reboot coprocessor MCU (0x5141) if motor continues
      this->emergency_stop_triggered_ = true;
      this->emergency_stop_time_ = now_ms;

      if (this->status_text_sensor_ != nullptr && this->calib_state_ == CALIB_IDLE)
        this->status_text_sensor_->publish_state("Safety Cutoff Triggered");
    }
  }

  // If emergency stop was triggered and motor didn't report complete within 1.5s, hard reboot coprocessor MCU
  if (this->emergency_stop_triggered_ && (now_ms - this->emergency_stop_time_ > 1500)) {
    this->emergency_stop_triggered_ = false;
    ESP_LOGW(TAG, "Dispense failsafe: rebooting coprocessor MCU via 0x5141 to cut motor PWM");
    this->send_frame_(0x22, OPCODE_REBOOT_MCU, 0x00, {});
  }

  // Calibration Settling State Handler (measures settled kibble weight after 3.5s)
  if (this->calib_state_ == CALIB_SETTLING) {
    if (now_ms - this->calib_timer_ >= 3500) {
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

  // Minute schedule tick and daily midnight portions reset
  if (this->time_ != nullptr) {
    ESPTime now = this->time_->now();
    if (now.is_valid()) {
      if (now.day_of_year != this->last_day_of_year_) {
        this->last_day_of_year_ = now.day_of_year;
        this->portions_today_ = 0;
        if (this->portions_today_sensor_ != nullptr)
          this->portions_today_sensor_->publish_state(0);
      }
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

void PPFR361SComponent::send_frame_(uint8_t frame_type, uint16_t opcode,
                                   uint8_t status, const std::vector<std::pair<uint8_t, std::vector<uint8_t>>> &klv_items) {
  // Encode inner KLV payload:
  // Byte 0: Protocol Version (Fixed 0x02)
  // Bytes 1-2: Opcode (Little-endian uint16_t)
  // Byte 3: Status code (0x00 for TX command)
  // Bytes 4+: KLV items [Key (1B)][Len (1B)][Value (Len B)]
  std::vector<uint8_t> inner;
  inner.push_back(0x02); // Fixed Protocol Version 0x02 for SC95F8766P coprocessor
  inner.push_back(static_cast<uint8_t>(opcode & 0xFF));
  inner.push_back(static_cast<uint8_t>((opcode >> 8) & 0xFF));
  inner.push_back(status);

  for (const auto &item : klv_items) {
    inner.push_back(item.first); // Key ID
    inner.push_back(static_cast<uint8_t>(item.second.size() & 0xFF)); // 1-byte length in SC95F protocol
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

  ESP_LOGI(TAG, "RAW TX FRAME (%d bytes, Opcode 0x%04X): %s", (int)frame.size(), opcode, format_hex_pretty(frame.data(), frame.size()).c_str());
  this->write_array(frame.data(), frame.size());
}

void PPFR361SComponent::send_ack_(uint8_t rx_seq, uint16_t opcode, uint8_t status) {
  std::vector<uint8_t> inner;
  inner.push_back(0x02); // Fixed Protocol Version 0x02
  inner.push_back(static_cast<uint8_t>(opcode & 0xFF));
  inner.push_back(static_cast<uint8_t>((opcode >> 8) & 0xFF));
  inner.push_back(status);

  uint16_t payload_len = static_cast<uint16_t>(inner.size());
  std::vector<uint8_t> frame;
  frame.reserve(payload_len + 6);
  frame.push_back(FRAME_HEADER);
  frame.push_back(0x12); // ACK frame type
  frame.push_back(rx_seq);
  frame.push_back(static_cast<uint8_t>(payload_len & 0xFF));
  frame.push_back(static_cast<uint8_t>((payload_len >> 8) & 0xFF));
  frame.push_back(0x00);
  frame.insert(frame.end(), inner.begin(), inner.end());
  frame[5] = this->calculate_checksum_(frame.data(), frame.size());

  ESP_LOGI(TAG, "RAW TX ACK (Seq 0x%02X, Opcode 0x%04X): %s", rx_seq, opcode, format_hex_pretty(frame.data(), frame.size()).c_str());
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

  ESP_LOGI(TAG, "RAW FRAME (%d bytes): %s", (int)len, format_hex_pretty(frame, len).c_str());
  uint8_t frame_type = frame[1];
  uint8_t rx_seq = frame[2];
  uint8_t proto_ver = frame[6];
  uint16_t opcode = frame[7] | (static_cast<uint16_t>(frame[8]) << 8);
  uint8_t status = frame[9];

  // Auto-ACK incoming request frames from coprocessor (frame_type 0x22)
  if (frame_type == 0x22) {
    this->send_ack_(rx_seq, opcode, 0x00);
  }

  // Parse KLV elements from frame[10] to frame[len-1]
  // In SC95F8766P hardware protocol, key length is 1 byte: [KeyID (1B)][Length (1B)][Value (Len B)]
  std::map<uint8_t, std::vector<uint8_t>> klv_map;
  size_t idx = 10;
  while (idx + 2 <= len) {
    uint8_t key_id = frame[idx];
    uint8_t item_len = frame[idx + 1];
    idx += 2;
    if (idx + item_len > len) break;
    std::vector<uint8_t> val(frame + idx, frame + idx + item_len);
    klv_map[key_id] = val;
    idx += item_len;
  }

  ESP_LOGI(TAG, "UART RX: Opcode 0x%04X, ProtoVer 0x%02X, Status %d, KLV count %d", opcode, proto_ver, status, (int)klv_map.size());
  for (const auto &kv : klv_map) {
    ESP_LOGI(TAG, "  -> KLV Key %d (len %d): %s", kv.first, (int)kv.second.size(), format_hex_pretty(kv.second).c_str());
  }
  this->handle_opcode_(opcode, status, klv_map);
  return true;
}

void PPFR361SComponent::handle_opcode_(uint16_t opcode, uint8_t status,
                                      const std::map<uint8_t, std::vector<uint8_t>> &klv) {
  switch (opcode) {
    case OPCODE_STATUS_POLL:   // 0x5592 - Device Status Query Response
    case OPCODE_STATUS_REPORT: { // 0x5593 - Full Telemetry Status Report
      // Key 3: child_lock (0 = Unlocked, 1 = Locked)
      if (klv.count(3) && !klv.at(3).empty()) {
        bool locked = (klv.at(3)[0] != 0);
        if (this->child_lock_switch_ != nullptr && !this->is_dispensing_)
          this->child_lock_switch_->publish_state(locked);
      }

      // Key 4: food_remind (Food Hopper Low: 0 = OK, 1 = Low)
      if (klv.count(4) && !klv.at(4).empty()) {
        bool food_low = (klv.at(4)[0] != 0);
        if (this->food_low_sensor_ != nullptr)
          this->food_low_sensor_->publish_state(food_low);
      }

      // Key 5: battery_percent (0 = not installed / absent, 1-100% installed)
      if (klv.count(5) && !klv.at(5).empty()) {
        uint8_t bat = klv.at(5)[0];
        bool installed = (bat > 0 && bat <= 100);
        if (this->battery_installed_sensor_ != nullptr)
          this->battery_installed_sensor_->publish_state(installed);
        if (this->battery_level_sensor_ != nullptr) {
          if (installed) {
            this->battery_level_sensor_->publish_state(static_cast<float>(bat));
          } else {
            this->battery_level_sensor_->publish_state(NAN);
          }
        }
      } else {
        if (this->battery_installed_sensor_ != nullptr)
          this->battery_installed_sensor_->publish_state(false);
        if (this->battery_level_sensor_ != nullptr)
          this->battery_level_sensor_->publish_state(NAN);
      }

      // Update desiccant days remaining (30-day countdown matching stock APK)
      if (this->desiccant_days_sensor_ != nullptr) {
        uint32_t now_epoch = this->time_ != nullptr ? this->time_->now().timestamp : 0;
        uint8_t days_left = 30;
        if (now_epoch > 1700000000 && this->storage_.last_desiccant_reset_epoch > 0) {
          uint32_t elapsed_days = (now_epoch - this->storage_.last_desiccant_reset_epoch) / 86400;
          days_left = elapsed_days >= 30 ? 0 : (30 - elapsed_days);
        }
        this->desiccant_days_sensor_->publish_state(days_left);
      }

      // Key 6: power_mode (0 = AC Adapter, 1 = Battery Backup)
      if (klv.count(6) && !klv.at(6).empty()) {
        bool ac_power = (klv.at(6)[0] == 0);
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

      // Key 7: error_code (0 = OK, 1 = Jammed, 2 = Chute Blocked)
      if (klv.count(7) && !klv.at(7).empty()) {
        uint8_t err = klv.at(7)[0];
        bool jammed = (err == 1);
        if (this->motor_jammed_sensor_ != nullptr)
          this->motor_jammed_sensor_->publish_state(jammed);
        if (err == 1 && this->status_text_sensor_ != nullptr)
          this->status_text_sensor_->publish_state("Motor Jammed");
        else if (err == 2 && this->status_text_sensor_ != nullptr)
          this->status_text_sensor_->publish_state("Outlet Blocked");
      }

      // Key 11 (0x0B): remaining_weight (grams, int16 LE)
      if (klv.count(11) && klv.at(11).size() >= 2) {
        int16_t weight = static_cast<int16_t>(klv.at(11)[0] | (klv.at(11)[1] << 8));
        if (this->bowl_weight_sensor_ != nullptr)
          this->bowl_weight_sensor_->publish_state(static_cast<float>(weight));
        if (this->bowl_connected_sensor_ != nullptr)
          this->bowl_connected_sensor_->publish_state(true);
      }

      // Only publish Online / Standby if not currently dispensing, calibrating, or holding completion status
      if (!this->is_dispensing_ && this->calib_state_ == CALIB_IDLE &&
          (millis() - this->last_feed_complete_time_ >= 5000)) {
        if (this->status_text_sensor_ != nullptr)
          this->status_text_sensor_->publish_state("Online / Standby");
      }
      break;
    }

    case OPCODE_DISPENSE_RESULT: { // 0x5596 - Dispense Complete Telemetry
      this->is_dispensing_ = false;
      this->emergency_stop_triggered_ = false;
      uint16_t mcu_total = 0;
      uint8_t code = 0;

      if (klv.count(2) && klv.at(2).size() >= 2)
        mcu_total = klv.at(2)[0] | (static_cast<uint16_t>(klv.at(2)[1]) << 8);
      else if (klv.count(2) && !klv.at(2).empty())
        mcu_total = klv.at(2)[0];

      if (klv.count(3) && !klv.at(3).empty())
        code = klv.at(3)[0];

      ESP_LOGI(TAG, "Feed result: weight=%dg, code=0x%02X", mcu_total, code);

      // Restore child lock if it was temporarily disengaged for remote feeding
      if (this->restore_child_lock_after_feed_) {
        this->restore_child_lock_after_feed_ = false;
        ESP_LOGI(TAG, "Restoring child lock to ON following remote dispense completion");
        this->send_frame_(0x22, OPCODE_CHILD_LOCK, 0x00, {{1, {0x01}}});
      }

      if (mcu_total == 0 && (code & 0x01) == 0) {
        ESP_LOGW(TAG, "Feed reported 0g dispensed (coprocessor locked or feed aborted).");
        this->dispense_requested_portions_ = 0;
        if (this->calib_state_ == CALIB_DISPENSING) {
          ESP_LOGE(TAG, "Calibration failed: Coprocessor locked or 0g dispensed!");
          this->calib_state_ = CALIB_IDLE;
          if (this->status_text_sensor_ != nullptr)
            this->status_text_sensor_->publish_state("Calibration Failed: Locked / 0g");
        } else if (this->status_text_sensor_ != nullptr && this->calib_state_ == CALIB_IDLE) {
          this->status_text_sensor_->publish_state("Feed Aborted (0g / Locked)");
        }
        break;
      }

      uint16_t delta_portions = this->dispense_requested_portions_ > 0 ? this->dispense_requested_portions_ : 1;
      this->dispense_requested_portions_ = 0;

      // Handle Portion Calibration State Machine
      if (this->calib_state_ == CALIB_DISPENSING) {
        if (code == 0 || (code & 0x01)) {
          ESP_LOGI(TAG, "Calibration test dispense finished (%d portions). Waiting 3.5s for load cell settling...", delta_portions);
          this->calib_state_ = CALIB_SETTLING;
          this->calib_timer_ = millis();
          if (this->status_text_sensor_ != nullptr)
            this->status_text_sensor_->publish_state("Calibrating: Settling & weighing...");
          this->set_timeout("calib_poll_1", 1500, [this]() { this->poll_status_(); });
          this->set_timeout("calib_poll_2", 2800, [this]() { this->poll_status_(); });
        } else {
          ESP_LOGE(TAG, "Calibration failed: Motor jam or chute error during test dispense!");
          this->calib_state_ = CALIB_IDLE;
          if (this->status_text_sensor_ != nullptr)
            this->status_text_sensor_->publish_state("Calibration Failed: Jam/Chute error");
        }
      }

      if (code == 0 || (code & 0x01)) {
        if (delta_portions > 0) {
          this->portions_today_ += delta_portions;
          if (this->portions_today_sensor_ != nullptr)
            this->portions_today_sensor_->publish_state(this->portions_today_);

          float grams = mcu_total > 0 ? static_cast<float>(mcu_total) : (static_cast<float>(delta_portions) * this->storage_.grams_per_portion);
          if (this->last_feed_weight_sensor_ != nullptr)
            this->last_feed_weight_sensor_->publish_state(grams);

          if (this->status_text_sensor_ != nullptr && this->calib_state_ == CALIB_IDLE)
            this->status_text_sensor_->publish_state("Feeding Complete");
        }
        if (this->motor_jammed_sensor_ != nullptr)
          this->motor_jammed_sensor_->publish_state(false);

        this->last_feed_complete_time_ = millis();
        this->set_timeout("feed_complete_reset", 5000, [this]() {
          if (!this->is_dispensing_ && this->calib_state_ == CALIB_IDLE && this->status_text_sensor_ != nullptr) {
            this->status_text_sensor_->publish_state("Online / Standby");
          }
        });

        this->set_timeout("bowl_refresh", 2000, [this]() {
          this->poll_status_();
        });
      } else if (code == 1 || (code & 0x02)) {
        ESP_LOGE(TAG, "FEED ERROR: Motor Jammed!");
        if (this->motor_jammed_sensor_ != nullptr)
          this->motor_jammed_sensor_->publish_state(true);
        if (this->status_text_sensor_ != nullptr)
          this->status_text_sensor_->publish_state("Motor Jammed");
      } else if (code == 2 || (code & 0x04)) {
        ESP_LOGW(TAG, "FEED WARNING: Chute Blocked!");
        if (this->status_text_sensor_ != nullptr)
          this->status_text_sensor_->publish_state("Outlet Blocked");
      }
      break;
    }

    case OPCODE_FEED_CMD: { // Feed Command Response (0x5590)
      if (status == 0) {
        ESP_LOGI(TAG, "Feed request accepted by coprocessor (Status 0). Motor running...");
        this->is_dispensing_ = true;
        this->dispense_start_time_ = millis();
        if (this->status_text_sensor_ != nullptr && this->calib_state_ == CALIB_IDLE)
          this->status_text_sensor_->publish_state("Dispensing...");
      } else {
        ESP_LOGE(TAG, "Feed request rejected by coprocessor with status %d (0x%02X)", status, status);
        this->is_dispensing_ = false;
        if (this->status_text_sensor_ != nullptr)
          this->status_text_sensor_->publish_state("Feed Rejected");
      }
      break;
    }

    case OPCODE_CHILD_LOCK: { // 0x5104 - Child Lock ACK
      ESP_LOGI(TAG, "Child lock ACK from coprocessor: status %d", status);
      break;
    }

    case OPCODE_TARE_BOWL: { // 0x55A3 - Tare Result
      // In stock firmware (s_zero_result / pet_feeder_report_zero_result_event):
      // Key 1: Status Code (0 = success, 1 = bowlConnAbnormal, 2 = weightFluctuation, 3 = bowlNotPlaced)
      // Key 2: Source Flag (1 = remote app command, 0 = hardware button)
      uint8_t result = status;
      if (klv.count(1) && !klv.at(1).empty()) {
        result = klv.at(1)[0];
      }

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
        ESP_LOGW(TAG, "Tare failed: Bowl connection abnormal (bowlConnAbnormal)");
        if (this->calib_state_ == CALIB_TARING) this->calib_state_ = CALIB_IDLE;
        if (this->bowl_connected_sensor_ != nullptr)
          this->bowl_connected_sensor_->publish_state(false);
        if (this->status_text_sensor_ != nullptr)
          this->status_text_sensor_->publish_state("Bowl Connection Error");
      } else if (result == 2) {
        ESP_LOGW(TAG, "Tare failed: Weight Fluctuating / Unstable (weightFluctuation)");
        if (this->calib_state_ == CALIB_TARING) this->calib_state_ = CALIB_IDLE;
        if (this->status_text_sensor_ != nullptr)
          this->status_text_sensor_->publish_state("Tare Failed: Unstable Weight");
      } else if (result == 3) {
        ESP_LOGW(TAG, "Tare failed: Bowl Not Placed / Missing (bowlNotPlaced)");
        if (this->calib_state_ == CALIB_TARING) this->calib_state_ = CALIB_IDLE;
        if (this->bowl_connected_sensor_ != nullptr)
          this->bowl_connected_sensor_->publish_state(false);
        if (this->status_text_sensor_ != nullptr)
          this->status_text_sensor_->publish_state("Bowl Not Placed");
      } else {
        ESP_LOGW(TAG, "Bowl scale tare failed (result code %d)", result);
        if (this->calib_state_ == CALIB_TARING) this->calib_state_ = CALIB_IDLE;
        if (this->status_text_sensor_ != nullptr)
          this->status_text_sensor_->publish_state("Tare Failed");
      }

      this->set_timeout("tare_poll", 800, [this]() {
        this->poll_status_();
      });
      break;
    }

    case OPCODE_CLOCK_REQ: { // 0x5595 - Coprocessor requests timestamp sync
      uint32_t epoch_sec = 0;
      if (this->time_ != nullptr) {
        ESPTime now = this->time_->now();
        if (now.is_valid()) epoch_sec = now.timestamp;
      }
      ESP_LOGI(TAG, "Coprocessor requested timestamp via 0x5595: syncing epoch %lu", (unsigned long)epoch_sec);
      std::vector<std::pair<uint8_t, std::vector<uint8_t>>> items;
      items.push_back({1, {
        static_cast<uint8_t>(epoch_sec & 0xFF),
        static_cast<uint8_t>((epoch_sec >> 8) & 0xFF),
        static_cast<uint8_t>((epoch_sec >> 16) & 0xFF),
        static_cast<uint8_t>((epoch_sec >> 24) & 0xFF)
      }});
      this->send_frame_(0x22, OPCODE_CLOCK_REQ, 0x00, items);
      break;
    }

    case OPCODE_BUTTON_EVENT: { // 0x5597 - Hardware Reminder / Button Notification
      uint8_t ev = 0;
      if (klv.count(7) && !klv.at(7).empty()) {
        ev = klv.at(7)[0];
      } else if (klv.count(1) && !klv.at(1).empty()) {
        ev = klv.at(1)[0];
      }
      ESP_LOGI(TAG, "Hardware event from coprocessor (0x5597): 0x%02X", ev);
      // NOTE: Coprocessor MCU directly handles front button physical dispense internally;
      // do not inject a software feed command here to avoid infinite feedback loops.
      break;
    }

    case OPCODE_PLAY_AUDIO: { // 0x5598 - Play Audio Chime Notification
      ESP_LOGI(TAG, "Coprocessor requested audio chime prompt playback (0x5598)");
      if (this->sleep_mode_switch_ != nullptr && this->sleep_mode_switch_->state) {
        ESP_LOGI(TAG, "Sleep mode active: silencing meal prompt");
      } else {
        this->schedule_trigger_callback_.call();
      }
      break;
    }

    default:
      ESP_LOGV(TAG, "Unhandled Opcode 0x%04X received", opcode);
      break;
  }
}

void PPFR361SComponent::poll_status_() {
  // Opcode 0x5592: Device Status Query (Frame type 0x22 matching stock master commands)
  this->send_frame_(0x22, OPCODE_STATUS_POLL, 0x00, {});
}

void PPFR361SComponent::feed(uint16_t portions, bool sound) {
  if (portions == 0) portions = 1;
  if (portions > 20) portions = 20;

  float grams_per_portion = this->storage_.grams_per_portion > 0 ? this->storage_.grams_per_portion : 8.0f;
  uint16_t target_weight = static_cast<uint16_t>(std::round(portions * grams_per_portion));
  if (target_weight < 8) {
    target_weight = 8;
  }
  uint8_t feed_type = 0;

  ESP_LOGI(TAG, "Dispensing %d portion(s) (target %dg, type %d)...", portions, target_weight, feed_type);
  this->is_dispensing_ = true;
  this->dispense_start_time_ = millis();
  this->dispense_requested_portions_ = portions;
  this->dispense_timeout_ms_ = 25000;
  this->emergency_stop_triggered_ = false;

  if (this->status_text_sensor_ != nullptr && this->calib_state_ == CALIB_IDLE)
    this->status_text_sensor_->publish_state("Feeding...");

  // Interlock bypass: If child lock is active on the coprocessor, temporarily disengage it over UART
  // so remote feeding succeeds seamlessly without requiring physical interaction with the feeder button.
  if (this->child_lock_switch_ != nullptr && this->child_lock_switch_->state) {
    ESP_LOGI(TAG, "Child lock is ON: Temporarily unlocking coprocessor MCU via 0x5140 (00)...");
    this->restore_child_lock_after_feed_ = true;
    this->send_frame_(0x22, OPCODE_CHILD_LOCK, 0x00, {{1, {0x00}}});
    delay(60);
  } else {
    this->restore_child_lock_after_feed_ = false;
  }

  // Exact 3 keys matching stock protocol (pet_feeder_uart_set_food_output / executeGrain):
  // frame_type: 0x22 (SC95F protocol master request with ACK flag)
  // Key 1 (2B): Target Weight in Grams (uint16_t LE)
  // Key 2 (2B): Cutoff limit (0x0000)
  // Key 3 (1B): Feed Type (0 = remote meal command matching stock executeGrain)
  ESP_LOGI(TAG, "Sending food output command (0x5590): target=%dg, cutoff=0g, type=%d...",
           target_weight, feed_type);
  std::vector<std::pair<uint8_t, std::vector<uint8_t>>> items;
  items.push_back({1, {static_cast<uint8_t>(target_weight & 0xFF), static_cast<uint8_t>((target_weight >> 8) & 0xFF)}});
  items.push_back({2, {0x00, 0x00}});
  items.push_back({3, {feed_type}});

  this->send_frame_(0x22, OPCODE_FEED_CMD, 0x00, items);
}

void PPFR361SComponent::tare_bowl() {
  ESP_LOGI(TAG, "Zeroing bowl scale...");
  this->send_frame_(0x22, OPCODE_TARE_BOWL, 0x00, {});
  if (this->bowl_weight_sensor_ != nullptr)
    this->bowl_weight_sensor_->publish_state(0.0f);
  this->set_timeout("tare_refresh", 1500, [this]() {
    this->poll_status_();
  });
}

void PPFR361SComponent::reset_desiccant() {
  ESP_LOGI(TAG, "Resetting 30-day silica desiccant replacement timer...");
  if (this->time_ != nullptr && this->time_->now().is_valid()) {
    this->storage_.last_desiccant_reset_epoch = this->time_->now().timestamp;
  } else {
    this->storage_.last_desiccant_reset_epoch = static_cast<uint32_t>(::time(nullptr));
  }
  this->save_schedule_to_nvs_();
  if (this->desiccant_days_sensor_ != nullptr)
    this->desiccant_days_sensor_->publish_state(30.0f);
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
  this->send_frame_(0x22, OPCODE_CHILD_LOCK, 0x00, items);
  if (this->child_lock_switch_ != nullptr)
    this->child_lock_switch_->publish_state(locked);
}

void PPFR361SComponent::set_slow_feed(bool slow) {
  ESP_LOGI(TAG, "Setting slow feed mode: %s", slow ? "ON" : "OFF");
  std::vector<std::pair<uint8_t, std::vector<uint8_t>>> items;
  items.push_back({1, {static_cast<uint8_t>(slow ? 1 : 0)}});
  this->send_frame_(0x22, OPCODE_SLOW_FEED, 0x00, items);
  if (this->slow_feed_switch_ != nullptr)
    this->slow_feed_switch_->publish_state(slow);
}

void PPFR361SComponent::set_sleep_mode(bool sleep) {
  ESP_LOGI(TAG, "Setting night sleep mode: %s", sleep ? "ON" : "OFF");
  std::vector<std::pair<uint8_t, std::vector<uint8_t>>> items;
  items.push_back({1, {static_cast<uint8_t>(sleep ? 1 : 0)}});
  items.push_back({2, {0x00}});
  this->send_frame_(0x22, OPCODE_SLEEP_MODE, 0x00, items);
  if (this->sleep_mode_switch_ != nullptr)
    this->sleep_mode_switch_->publish_state(sleep);
}

void PPFR361SComponent::set_wifi_led(uint8_t mode) {
  std::vector<std::pair<uint8_t, std::vector<uint8_t>>> items;
  items.push_back({1, {mode}});
  this->send_frame_(0x22, OPCODE_WIFI_LED, 0x00, items);
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
  this->send_frame_(0x22, OPCODE_CLOCK_SYNC, 0x00, items);

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
  // Schedules are evaluated locally on ESP32 in evaluate_schedules_().
  // Disassembly of app_active.elf proves Opcode 0x55A6 is pet_feeder_uart_set_temperature_correct,
  // NOT schedule synchronization. Do NOT send multi-byte schedule frames to 0x55A6.
  this->update_schedule_sensors_();
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
  const esp_partition_t *running = esp_ota_get_running_partition();
  if (running != nullptr && strcmp(running->label, "ota_1") == 0) {
    ESP_LOGE(TAG, "Rollback aborted: Feeder is ALREADY running on factory partition 'ota_1'!");
    return;
  }

  const esp_partition_t *ota1 = esp_partition_find_first(ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_APP_OTA_1, "ota_1");
  if (ota1 != nullptr) {
    esp_err_t err = esp_ota_set_boot_partition(ota1);
    if (err == ESP_OK) {
      ESP_LOGW(TAG, "Boot partition set to 'ota_1' successfully! Rebooting into stock factory firmware in 2 seconds...");
      delay(2000);
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
