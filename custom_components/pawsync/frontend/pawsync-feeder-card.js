/**
 * Pawsync Feeder Lovelace Custom Card
 * Replicating the official Pawsync Mobile App experience for Home Assistant.
 * 
 * Features:
 * - Multi-Feeder Support (Auto-discovery & tab switcher)
 * - Real-Time Bowl Weight & Pet Eating live glow pulse
 * - Hopper, AC Power, Battery, and Scale status indicators
 * - Dynamic Calibrated Kibble Density (reads number.*_grams_per_portion_kibble_calibration)
 * - 4 Key Stats: Planned Serving Today, Next Meal, Last Eaten (Weight & Time), Total Eaten Today
 * - Collapsible Feeding Schedule (Defaults to collapsed state to conserve card space)
 * - Quick Manual Dispense with portion stepper (- / +) and Scale Tare
 * - Graphical Meal Schedule Manager (10 slots, day pills, enable/disable toggles)
 * - App-Replica Interactive Meal Editor (Time picker, Day pills with presets, Portions stepper, Sound chime)
 * - Direct NVS persistence via ESPHome native API actions
 * - Visual Card Editor for Lovelace UI
 */

const CARD_VERSION = "1.2.2";

console.info(
  `%c PAWSYNC-FEEDER-CARD %c v${CARD_VERSION} `,
  "color: white; background: #ff9800; font-weight: 700; border-radius: 3px 0 0 3px;",
  "color: #ff9800; background: #263238; font-weight: 700; border-radius: 0 3px 3px 0;"
);

class PawsyncFeederCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._selectedFeederIdx = 0;
    this._manualPortions = 1;
    this._scheduleCollapsed = true; // Default to collapsed state
    this._editingMeal = null; // null or meal object being edited
    this._localSchedules = {}; // cache of local schedules per feeder
  }

  setConfig(config) {
    this._config = {
      title: "Pet Feeder",
      grams_per_portion: 9.0,
      show_header: true,
      show_quick_feed: true,
      show_schedule: true,
      default_collapsed: true,
      ...config,
    };
    if (this._config.default_collapsed !== undefined) {
      this._scheduleCollapsed = this._config.default_collapsed;
    }
    this._render();
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;

    // Discover feeders if not explicitly defined
    this._feeders = this._resolveFeeders();

    // Check if we need to update schedule cache from schedule summary
    this._syncSchedulesFromStates();

    // Check if active feeder states changed
    if (!oldHass || this._hasRelevantStateChanged(oldHass, hass)) {
      this._render();
    }
  }

  getCardSize() {
    return this._scheduleCollapsed ? 5 : 9;
  }

  static getConfigElement() {
    return document.createElement("pawsync-feeder-card-editor");
  }

  static getStubConfig(hass) {
    const entities = Object.keys(hass.states);
    const weightEntity = entities.find((e) => e.includes("bowl_weight") && e.includes("feeder"));
    let prefix = "pawsync_ppf_r361s_feeder";
    if (weightEntity) {
      prefix = weightEntity.replace(/^sensor\./, "").replace(/_bowl_weight$/, "");
    }
    return {
      type: "custom:pawsync-feeder-card",
      title: "Pawsync Smart Feeder",
      feeder_prefix: prefix,
      grams_per_portion: 9.0,
      default_collapsed: true,
    };
  }

  _resolveFeeders() {
    if (this._config.feeders && Array.isArray(this._config.feeders) && this._config.feeders.length > 0) {
      return this._config.feeders;
    }

    if (this._config.feeder_prefix) {
      return [
        {
          name: this._config.title || "Pawsync Feeder",
          prefix: this._config.feeder_prefix,
        },
      ];
    }

    // Auto-discover all feeders in HA
    const discovered = [];
    if (!this._hass) return discovered;

    const entities = Object.keys(this._hass.states);
    const weightSensors = entities.filter(
      (e) => e.startsWith("sensor.") && e.endsWith("_bowl_weight")
    );

    weightSensors.forEach((ws) => {
      const prefix = ws.replace(/^sensor\./, "").replace(/_bowl_weight$/, "");
      const stateObj = this._hass.states[ws];
      const friendly = (stateObj.attributes && stateObj.attributes.friendly_name)
        ? stateObj.attributes.friendly_name.replace(" Bowl Weight", "").replace(" Feeder", "")
        : prefix;

      discovered.push({
        name: friendly,
        prefix: prefix,
      });
    });

    if (discovered.length === 0) {
      discovered.push({
        name: "Pawsync Feeder",
        prefix: "pawsync_ppf_r361s_feeder",
      });
    }

    return discovered;
  }

  _getActiveFeeder() {
    if (!this._feeders || this._feeders.length === 0) {
      return { name: "Feeder", prefix: "pawsync_ppf_r361s_feeder" };
    }
    const idx = Math.min(this._selectedFeederIdx, this._feeders.length - 1);
    return this._feeders[idx];
  }

  _getEntity(domain, suffix) {
    if (!this._hass) return null;
    const feeder = this._getActiveFeeder();
    let entityId = `${domain}.${feeder.prefix}_${suffix}`;
    if (this._hass.states[entityId]) return this._hass.states[entityId];

    const searchKeys = Object.keys(this._hass.states).filter(
      (k) => k.startsWith(`${domain}.`) && k.endsWith(`_${suffix}`)
    );
    if (searchKeys.length > 0) {
      const match = searchKeys.find((k) => k.includes(feeder.prefix));
      return match ? this._hass.states[match] : this._hass.states[searchKeys[0]];
    }
    return null;
  }

  _getKibbleDensity() {
    // Read calibrated density from number.<feeder>_grams_per_portion_kibble_calibration
    const densityEntity = this._getEntity("number", "grams_per_portion_kibble_calibration");
    if (densityEntity && densityEntity.state && !isNaN(parseFloat(densityEntity.state))) {
      const val = parseFloat(densityEntity.state);
      if (val > 0) return val;
    }
    return parseFloat(this._config.grams_per_portion) || 9.0;
  }

  _hasRelevantStateChanged(oldHass, newHass) {
    const feeder = this._getActiveFeeder();
    const keysToCheck = [
      `sensor.${feeder.prefix}_bowl_weight`,
      `binary_sensor.${feeder.prefix}_pet_eating`,
      `sensor.${feeder.prefix}_portions_today`,
      `sensor.${feeder.prefix}_today_s_schedule_summary`,
      `binary_sensor.${feeder.prefix}_food_level_low`,
      `binary_sensor.${feeder.prefix}_ac_power_connected`,
      `sensor.${feeder.prefix}_battery_level`,
      `sensor.${feeder.prefix}_next_scheduled_meal`,
      `number.${feeder.prefix}_grams_per_portion_kibble_calibration`,
      `sensor.david_${feeder.prefix}_last_meal_amount_consumed`,
      `sensor.david_${feeder.prefix}_last_meal_time`,
      `sensor.${feeder.prefix}_last_meal_amount_consumed`,
      `sensor.${feeder.prefix}_last_meal_time`,
      `sensor.${feeder.prefix}_total_eaten_today`,
    ];
    for (const key of keysToCheck) {
      if (oldHass.states[key] !== newHass.states[key]) return true;
    }
    return false;
  }

  _syncSchedulesFromStates() {
    const feeder = this._getActiveFeeder();
    const summarySensor = this._getEntity("sensor", "today_s_schedule_summary");
    if (!this._localSchedules[feeder.prefix]) {
      this._localSchedules[feeder.prefix] = Array.from({ length: 10 }, (_, i) => ({
        meal: i + 1,
        enabled: false,
        time: i === 0 ? "08:00" : i === 1 ? "18:00" : "12:00",
        days: "All",
        portions: i === 0 ? 2 : i === 1 ? 3 : 1,
        sound: true,
      }));
    }

    if (summarySensor && summarySensor.state && summarySensor.state !== "No active meals today") {
      const parts = summarySensor.state.split("|").map((p) => p.trim());
      parts.forEach((part) => {
        const match = part.match(/M(\d+):\s*(\d{1,2}:\d{2})\s*\((\d+)p\)/);
        if (match) {
          const mealIdx = parseInt(match[1], 10) - 1;
          if (mealIdx >= 0 && mealIdx < 10) {
            this._localSchedules[feeder.prefix][mealIdx].enabled = true;
            this._localSchedules[feeder.prefix][mealIdx].time = match[2];
            this._localSchedules[feeder.prefix][mealIdx].portions = parseInt(match[3], 10);
          }
        }
      });
    }
  }

  _calculatePlannedToday(density) {
    const feeder = this._getActiveFeeder();
    const schedules = this._localSchedules[feeder.prefix] || [];
    const days = ["su", "mo", "tu", "we", "th", "fr", "sa"];
    const todayIdx = new Date().getDay();
    const todayKey = days[todayIdx];

    let totalPortions = 0;
    schedules.forEach((m) => {
      if (m.enabled) {
        const mask = this._getDaysMask(m.days);
        if (mask[todayKey]) {
          totalPortions += (m.portions || 1);
        }
      }
    });

    const totalGrams = (totalPortions * density).toFixed(0);
    return {
      portions: totalPortions,
      grams: totalGrams,
    };
  }

  _calculateEatenToday(lastMealAmount, lastMealTime) {
    const feeder = this._getActiveFeeder();

    // 1. Check if a native sensor exists in HA
    const eatenSensor = this._getEntity("sensor", "total_eaten_today");
    if (eatenSensor && eatenSensor.state && !isNaN(parseFloat(eatenSensor.state))) {
      return parseFloat(eatenSensor.state).toFixed(1);
    }

    // 2. Use browser's LOCAL calendar date (NOT UTC toISOString!)
    const now = new Date();
    const localYear = now.getFullYear();
    const localMonth = String(now.getMonth() + 1).padStart(2, "0");
    const localDay = String(now.getDate()).padStart(2, "0");
    const todayLocal = `${localYear}-${localMonth}-${localDay}`;

    const storageKey = `pawsync_eaten_${feeder.prefix}_${todayLocal}`;
    let todayEaten = 0;
    try {
      todayEaten = parseFloat(localStorage.getItem(storageKey) || "0");
    } catch (_) {}

    // 3. Inspect last_meal_amount and last_meal_time
    if (lastMealAmount && lastMealAmount.state && !isNaN(parseFloat(lastMealAmount.state))) {
      const lastAmount = parseFloat(lastMealAmount.state);

      let isMealFromToday = false;
      if (lastMealTime && lastMealTime.state && lastMealTime.state !== "unknown") {
        const mealTimeStr = String(lastMealTime.state).trim();
        // Check if date portion matches today (e.g. "2026-10-25" or "2026-10-26")
        if (mealTimeStr.includes(todayLocal)) {
          isMealFromToday = true;
        } else {
          // If date in last_meal_time string has a date e.g. YYYY-MM-DD
          const match = mealTimeStr.match(/^(\d{4}-\d{2}-\d{2})/);
          if (match) {
            // Also accept if within 18 hours of current time
            const mealDate = new Date(mealTimeStr.replace(" ", "T"));
            if (!isNaN(mealDate.getTime())) {
              const diffHours = (now.getTime() - mealDate.getTime()) / (1000 * 60 * 60);
              if (diffHours >= 0 && diffHours < 18) {
                isMealFromToday = true;
              }
            }
          }
        }
      } else {
        // Fallback: If amount > 0, assume it was eaten in active session
        isMealFromToday = true;
      }

      if (isMealFromToday && lastAmount > 0) {
        if (todayEaten < lastAmount) {
          todayEaten = lastAmount;
          try {
            localStorage.setItem(storageKey, todayEaten.toFixed(1));
          } catch (_) {}
        }

        // Accumulate if new distinct timestamp appears
        if (lastMealTime && lastMealTime.state) {
          const lastRecordedKey = `pawsync_last_recorded_ts_${feeder.prefix}`;
          try {
            const lastRecorded = localStorage.getItem(lastRecordedKey);
            if (lastRecorded && lastRecorded !== String(lastMealTime.state)) {
              todayEaten += lastAmount;
              localStorage.setItem(storageKey, todayEaten.toFixed(1));
            }
            localStorage.setItem(lastRecordedKey, String(lastMealTime.state));
          } catch (_) {}
        }
      }
    }

    return todayEaten > 0 ? todayEaten.toFixed(1) : "0.0";
  }

  _callService(domain, service, data) {
    if (!this._hass) return;
    this._hass.callService(domain, service, data);
  }

  _feed(portions) {
    const feeder = this._getActiveFeeder();
    const serviceName = `${feeder.prefix.replace(/_ppf_r361s_feeder$/, "_feeder")}_feed`;
    this._callService("esphome", serviceName, { portions: portions });
  }

  _tare() {
    const feeder = this._getActiveFeeder();
    const tareButton = this._getEntity("button", "tare_bowl_scale");
    if (tareButton) {
      this._callService("button", "press", { entity_id: tareButton.entity_id });
    }
  }

  _toggleMeal(mealIdx, newEnabled) {
    const feeder = this._getActiveFeeder();
    const meal = this._localSchedules[feeder.prefix][mealIdx];
    meal.enabled = newEnabled;

    const actionService = `${feeder.prefix.replace(/_ppf_r361s_feeder$/, "_feeder")}_set_meal_schedule`;
    this._callService("esphome", actionService, {
      plan: 1,
      meal: meal.meal,
      enabled: meal.enabled,
      meal_time: meal.time,
      days: meal.days,
      portions: meal.portions,
      sound: meal.sound,
    });
    this._render();
  }

  _saveMealEditor(mealData) {
    const feeder = this._getActiveFeeder();
    const mealIdx = mealData.meal - 1;
    this._localSchedules[feeder.prefix][mealIdx] = { ...mealData };

    const actionService = `${feeder.prefix.replace(/_ppf_r361s_feeder$/, "_feeder")}_set_meal_schedule`;
    this._callService("esphome", actionService, {
      plan: 1,
      meal: mealData.meal,
      enabled: mealData.enabled,
      meal_time: mealData.time,
      days: mealData.days,
      portions: mealData.portions,
      sound: mealData.sound,
    });

    this._editingMeal = null;
    this._render();
  }

  _render() {
    if (!this._hass) return;

    const feeder = this._getActiveFeeder();
    const bowlWeight = this._getEntity("sensor", "bowl_weight");
    const petEating = this._getEntity("binary_sensor", "pet_eating");
    const foodLow = this._getEntity("binary_sensor", "food_level_low");
    const acPower = this._getEntity("binary_sensor", "ac_power_connected");
    const battery = this._getEntity("sensor", "battery_level");
    const scaleConn = this._getEntity("binary_sensor", "bowl_scale_connected");
    const motorJam = this._getEntity("binary_sensor", "motor_jammed");
    const lastMealAmount = this._getEntity("sensor", "last_meal_amount_consumed");
    const lastMealTime = this._getEntity("text_sensor", "last_meal_time") || this._getEntity("sensor", "last_meal_time");
    const nextMeal = this._getEntity("sensor", "next_scheduled_meal");

    // Dynamic calibrated kibble density
    const density = this._getKibbleDensity();

    const isEating = petEating && petEating.state === "on";
    const currentWeight = bowlWeight ? parseFloat(bowlWeight.state).toFixed(1) : "0.0";

    // 4 Key Small Stats Calculations
    const planned = this._calculatePlannedToday(density);
    const eatenToday = this._calculateEatenToday(lastMealAmount, lastMealTime);

    let nextMealDisplay = "Done for today";
    if (nextMeal && nextMeal.state && nextMeal.state !== "unknown") {
      nextMealDisplay = nextMeal.state.replace(" portions", "p").replace(" portion", "p");
    }

    let lastEatDisplay = "--";
    if (lastMealAmount && lastMealAmount.state && lastMealAmount.state !== "unknown") {
      const g = parseFloat(lastMealAmount.state).toFixed(1);
      let timeStr = "";
      if (lastMealTime && lastMealTime.state && lastMealTime.state !== "unknown") {
        const match = String(lastMealTime.state).match(/(\d{1,2}:\d{2})/);
        timeStr = match ? match[1] : String(lastMealTime.state);
      }
      lastEatDisplay = timeStr ? `${g}g · ${timeStr}` : `${g}g`;
    }

    const schedules = this._localSchedules[feeder.prefix] || [];
    const activeMealsCount = schedules.filter((m) => m.enabled).length;

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          font-family: var(--paper-font-body1_-_font-family, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif);
          --pawsync-primary: var(--primary-color, #ff9800);
          --pawsync-primary-rgb: 255, 152, 0;
          --pawsync-card-bg: var(--ha-card-background, var(--card-background-color, #ffffff));
          --pawsync-text: var(--primary-text-color, #212121);
          --pawsync-secondary-text: var(--secondary-text-color, #757575);
          --pawsync-surface: var(--secondary-background-color, #f5f5f5);
          --pawsync-border: var(--divider-color, rgba(0, 0, 0, 0.08));
          --pawsync-radius: 18px;
        }

        ha-card {
          background: var(--pawsync-card-bg);
          border-radius: var(--pawsync-radius);
          box-shadow: var(--ha-card-box-shadow, 0 4px 16px rgba(0,0,0,0.06));
          overflow: hidden;
          padding: 16px;
          position: relative;
        }

        /* Multi-Feeder Tabs */
        .feeder-tabs {
          display: flex;
          gap: 8px;
          overflow-x: auto;
          margin-bottom: 14px;
          padding-bottom: 4px;
        }
        .feeder-tab {
          padding: 6px 14px;
          border-radius: 20px;
          background: var(--pawsync-surface);
          color: var(--pawsync-secondary-text);
          font-size: 13px;
          font-weight: 600;
          cursor: pointer;
          border: 1px solid transparent;
          transition: all 0.2s ease;
          display: flex;
          align-items: center;
          gap: 6px;
          white-space: nowrap;
        }
        .feeder-tab.active {
          background: var(--pawsync-primary);
          color: #ffffff;
          box-shadow: 0 2px 8px rgba(var(--pawsync-primary-rgb), 0.35);
        }

        /* Feeder Header & Status Chips */
        .feeder-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;
        }
        .feeder-title {
          font-size: 18px;
          font-weight: 700;
          color: var(--pawsync-text);
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .status-chips {
          display: flex;
          gap: 6px;
          flex-wrap: wrap;
        }
        .chip {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 3px 8px;
          border-radius: 12px;
          font-size: 11px;
          font-weight: 600;
          background: var(--pawsync-surface);
          color: var(--pawsync-secondary-text);
        }
        .chip.ok { background: rgba(76, 175, 80, 0.12); color: #2e7d32; }
        .chip.warn { background: rgba(255, 152, 0, 0.15); color: #e65100; font-weight: 700; animation: pulse 2s infinite; }
        .chip.alert { background: rgba(244, 67, 54, 0.15); color: #c62828; font-weight: 700; }
        .chip.density { background: rgba(33, 150, 243, 0.12); color: #1565c0; font-weight: 600; }

        @keyframes pulse {
          0% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.04); opacity: 0.85; }
          100% { transform: scale(1); opacity: 1; }
        }

        /* Hero Bowl Card */
        .bowl-card {
          background: var(--pawsync-surface);
          border-radius: 16px;
          padding: 16px;
          text-align: center;
          position: relative;
          margin-bottom: 14px;
          border: 1px solid var(--pawsync-border);
          transition: all 0.3s ease;
        }
        .bowl-card.eating {
          border-color: var(--pawsync-primary);
          box-shadow: 0 0 16px rgba(var(--pawsync-primary-rgb), 0.45);
          animation: eatingGlow 1.8s infinite;
        }
        @keyframes eatingGlow {
          0% { box-shadow: 0 0 8px rgba(var(--pawsync-primary-rgb), 0.3); }
          50% { box-shadow: 0 0 20px rgba(var(--pawsync-primary-rgb), 0.6); }
          100% { box-shadow: 0 0 8px rgba(var(--pawsync-primary-rgb), 0.3); }
        }

        .eating-badge {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          background: var(--pawsync-primary);
          color: white;
          padding: 4px 12px;
          border-radius: 14px;
          font-size: 12px;
          font-weight: 700;
          margin-bottom: 8px;
        }
        .weight-display {
          display: flex;
          justify-content: center;
          align-items: baseline;
          gap: 4px;
          margin: 4px 0 2px 0;
        }
        .weight-number {
          font-size: 44px;
          font-weight: 800;
          color: var(--pawsync-text);
          line-height: 1;
        }
        .weight-unit {
          font-size: 18px;
          font-weight: 600;
          color: var(--pawsync-secondary-text);
        }
        .weight-sub {
          font-size: 12px;
          color: var(--pawsync-secondary-text);
          margin-bottom: 4px;
        }

        /* 4 Key Small Stats Grid */
        .stats-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 10px 12px;
          margin-top: 14px;
          padding-top: 14px;
          border-top: 1px solid var(--pawsync-border);
        }
        .stat-item {
          text-align: left;
          background: var(--pawsync-card-bg);
          padding: 8px 10px;
          border-radius: 10px;
          border: 1px solid var(--pawsync-border);
        }
        .stat-label {
          font-size: 10.5px;
          color: var(--pawsync-secondary-text);
          text-transform: uppercase;
          font-weight: 700;
          letter-spacing: 0.4px;
        }
        .stat-val {
          font-size: 13.5px;
          font-weight: 700;
          color: var(--pawsync-text);
          margin-top: 2px;
          display: flex;
          align-items: baseline;
          gap: 4px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .stat-sub {
          font-size: 11px;
          font-weight: normal;
          color: var(--pawsync-secondary-text);
        }

        /* Quick Feed Bar */
        .quick-feed-bar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          background: var(--pawsync-surface);
          border-radius: 14px;
          padding: 10px 14px;
          margin-bottom: 14px;
          border: 1px solid var(--pawsync-border);
        }
        .stepper {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .stepper-btn {
          width: 32px;
          height: 32px;
          border-radius: 50%;
          border: 1px solid var(--pawsync-border);
          background: var(--pawsync-card-bg);
          color: var(--pawsync-text);
          font-size: 18px;
          font-weight: 700;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: background 0.15s;
        }
        .stepper-btn:hover { background: var(--pawsync-surface); }
        .stepper-label {
          font-size: 13px;
          font-weight: 700;
          color: var(--pawsync-text);
          min-width: 80px;
          text-align: center;
        }
        .feed-btn {
          background: var(--pawsync-primary);
          color: white;
          border: none;
          border-radius: 10px;
          padding: 8px 16px;
          font-size: 13px;
          font-weight: 700;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 6px;
          transition: opacity 0.2s;
        }
        .feed-btn:hover { opacity: 0.9; }
        .tare-btn {
          background: transparent;
          color: var(--pawsync-secondary-text);
          border: 1px solid var(--pawsync-border);
          border-radius: 10px;
          padding: 8px 10px;
          font-size: 12px;
          font-weight: 600;
          cursor: pointer;
        }
        .tare-btn:hover { background: var(--pawsync-surface); }

        /* Collapsible Feeding Schedule Section */
        .schedule-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 12px 14px;
          background: var(--pawsync-surface);
          border-radius: 12px;
          cursor: pointer;
          border: 1px solid var(--pawsync-border);
          transition: background 0.2s;
          user-select: none;
        }
        .schedule-header:hover {
          background: rgba(var(--pawsync-primary-rgb), 0.05);
        }
        .schedule-title {
          font-size: 14px;
          font-weight: 700;
          color: var(--pawsync-text);
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .schedule-header-right {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .active-badge {
          font-size: 11px;
          font-weight: 600;
          padding: 3px 8px;
          border-radius: 10px;
          background: rgba(var(--pawsync-primary-rgb), 0.12);
          color: var(--pawsync-primary);
        }
        .chevron-icon {
          font-size: 13px;
          color: var(--pawsync-secondary-text);
          transition: transform 0.25s ease;
        }
        .chevron-icon.expanded {
          transform: rotate(90deg);
        }

        .schedule-body {
          margin-top: 10px;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .schedule-body.collapsed {
          display: none;
        }

        .meal-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .meal-card {
          background: var(--pawsync-surface);
          border-radius: 12px;
          padding: 10px 14px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          border: 1px solid var(--pawsync-border);
          transition: all 0.2s ease;
        }
        .meal-card.disabled {
          opacity: 0.6;
        }
        .meal-card:hover {
          border-color: rgba(var(--pawsync-primary-rgb), 0.5);
        }
        .meal-left {
          display: flex;
          flex-direction: column;
          gap: 4px;
          cursor: pointer;
          flex: 1;
        }
        .meal-main-row {
          display: flex;
          align-items: baseline;
          gap: 8px;
        }
        .meal-time {
          font-size: 16px;
          font-weight: 700;
          color: var(--pawsync-text);
        }
        .meal-tag {
          font-size: 11px;
          font-weight: 600;
          color: var(--pawsync-primary);
          background: rgba(var(--pawsync-primary-rgb), 0.1);
          padding: 2px 6px;
          border-radius: 6px;
        }
        .meal-days-row {
          display: flex;
          gap: 3px;
        }
        .day-pill {
          width: 18px;
          height: 18px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 9px;
          font-weight: 700;
          color: var(--pawsync-secondary-text);
          background: var(--pawsync-border);
        }
        .day-pill.active {
          background: var(--pawsync-primary);
          color: #ffffff;
        }
        .meal-right {
          display: flex;
          align-items: center;
          gap: 10px;
        }

        /* Switch Toggle */
        .switch {
          position: relative;
          display: inline-block;
          width: 38px;
          height: 22px;
        }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider {
          position: absolute;
          cursor: pointer;
          top: 0; left: 0; right: 0; bottom: 0;
          background-color: var(--pawsync-border);
          transition: .3s;
          border-radius: 22px;
        }
        .slider:before {
          position: absolute;
          content: "";
          height: 16px;
          width: 16px;
          left: 3px;
          bottom: 3px;
          background-color: white;
          transition: .3s;
          border-radius: 50%;
        }
        input:checked + .slider { background-color: var(--pawsync-primary); }
        input:checked + .slider:before { transform: translateX(16px); }

        .edit-icon-btn {
          background: transparent;
          border: none;
          cursor: pointer;
          color: var(--pawsync-secondary-text);
          padding: 4px;
          display: flex;
          align-items: center;
          font-size: 16px;
        }
        .edit-icon-btn:hover { color: var(--pawsync-primary); }

        .add-meal-btn {
          width: 100%;
          margin-top: 10px;
          padding: 10px;
          border-radius: 12px;
          background: transparent;
          border: 1px dashed var(--pawsync-primary);
          color: var(--pawsync-primary);
          font-size: 13px;
          font-weight: 700;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          transition: all 0.2s;
        }
        .add-meal-btn:hover {
          background: rgba(var(--pawsync-primary-rgb), 0.08);
        }

        /* Modal Editor Drawer */
        .modal-overlay {
          position: fixed;
          top: 0; left: 0; right: 0; bottom: 0;
          background: rgba(0, 0, 0, 0.5);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 9999;
          padding: 16px;
        }
        .modal-card {
          background: var(--pawsync-card-bg);
          border-radius: var(--pawsync-radius);
          width: 100%;
          max-width: 380px;
          padding: 20px;
          box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
          display: flex;
          flex-direction: column;
          gap: 16px;
        }
        .modal-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          border-bottom: 1px solid var(--pawsync-border);
          padding-bottom: 10px;
        }
        .modal-title {
          font-size: 16px;
          font-weight: 700;
          color: var(--pawsync-text);
        }
        .modal-close {
          background: transparent;
          border: none;
          font-size: 18px;
          cursor: pointer;
          color: var(--pawsync-secondary-text);
        }
        .modal-field {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .field-label {
          font-size: 12px;
          font-weight: 600;
          color: var(--pawsync-secondary-text);
          text-transform: uppercase;
        }
        .time-picker-row {
          display: flex;
          gap: 8px;
          align-items: center;
        }
        .time-input {
          font-size: 22px;
          font-weight: 700;
          padding: 8px 12px;
          border-radius: 10px;
          border: 1px solid var(--pawsync-border);
          background: var(--pawsync-surface);
          color: var(--pawsync-text);
          width: 100%;
          text-align: center;
        }

        /* Day Pills Selector */
        .day-selector-pills {
          display: flex;
          justify-content: space-between;
          gap: 4px;
        }
        .day-sel-btn {
          width: 36px;
          height: 36px;
          border-radius: 50%;
          border: 1px solid var(--pawsync-border);
          background: var(--pawsync-surface);
          color: var(--pawsync-secondary-text);
          font-size: 12px;
          font-weight: 700;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.2s;
        }
        .day-sel-btn.active {
          background: var(--pawsync-primary);
          color: #ffffff;
          border-color: var(--pawsync-primary);
          box-shadow: 0 2px 6px rgba(var(--pawsync-primary-rgb), 0.35);
        }
        .day-presets {
          display: flex;
          gap: 6px;
          margin-top: 4px;
        }
        .preset-chip {
          padding: 4px 10px;
          border-radius: 12px;
          background: var(--pawsync-surface);
          color: var(--pawsync-secondary-text);
          font-size: 11px;
          font-weight: 600;
          border: 1px solid var(--pawsync-border);
          cursor: pointer;
        }
        .preset-chip:hover {
          color: var(--pawsync-primary);
          border-color: var(--pawsync-primary);
        }

        .modal-actions {
          display: flex;
          justify-content: space-between;
          gap: 8px;
          margin-top: 8px;
          border-top: 1px solid var(--pawsync-border);
          padding-top: 12px;
        }
        .modal-btn {
          flex: 1;
          padding: 10px;
          border-radius: 10px;
          font-size: 13px;
          font-weight: 700;
          cursor: pointer;
          text-align: center;
          border: none;
        }
        .modal-btn.primary {
          background: var(--pawsync-primary);
          color: white;
        }
        .modal-btn.secondary {
          background: var(--pawsync-surface);
          color: var(--pawsync-text);
        }
        .modal-btn.danger {
          background: rgba(244, 67, 54, 0.12);
          color: #c62828;
        }
      </style>

      <ha-card>
        <!-- Multi-Feeder Tabs (if > 1 feeder) -->
        ${
          this._feeders.length > 1
            ? `
          <div class="feeder-tabs">
            ${this._feeders
              .map(
                (f, idx) => `
              <div class="feeder-tab ${idx === this._selectedFeederIdx ? "active" : ""}" data-idx="${idx}">
                <span>🐾</span> ${f.name}
              </div>
            `
              )
              .join("")}
          </div>
        `
            : ""
        }

        <!-- Header -->
        <div class="feeder-header">
          <div class="feeder-title">
            <span>🐾</span> ${feeder.name}
          </div>
          <div class="status-chips">
            <div class="chip density" title="Calibrated kibble density">
              ⚖️ ${density}g/p
            </div>
            ${
              foodLow
                ? `<div class="chip ${foodLow.state === "on" ? "warn" : "ok"}">
                     ${foodLow.state === "on" ? "⚠️ Food Low" : "✓ Food OK"}
                   </div>`
                : ""
            }
            ${
              acPower
                ? `<div class="chip ok">
                     ${acPower.state === "on" ? "⚡ AC" : `🔋 ${battery ? battery.state + "%" : "Battery"}`}
                   </div>`
                : ""
            }
            ${
              scaleConn && scaleConn.state === "off"
                ? `<div class="chip alert">Scale Disconnected</div>`
                : ""
            }
          </div>
        </div>

        <!-- Motor Jam Warning -->
        ${
          motorJam && motorJam.state === "on"
            ? `
          <div style="background: rgba(244,67,54,0.15); color: #c62828; padding: 8px 12px; border-radius: 10px; font-size: 12px; font-weight: 700; margin-bottom: 12px; display: flex; align-items: center; gap: 6px;">
            ⚠️ Motor Jammed! Check kibble chute.
          </div>
        `
            : ""
        }

        <!-- Hero Bowl Weight & Eating Live Detection -->
        <div class="bowl-card ${isEating ? "eating" : ""}">
          ${
            isEating
              ? `<div class="eating-badge">🐾 Pet is eating now!</div>`
              : ""
          }
          <div class="weight-display">
            <span class="weight-number">${currentWeight}</span>
            <span class="weight-unit">g</span>
          </div>
          <div class="weight-sub">Bowl Food Weight</div>

          <!-- 4 Small Stats Grid -->
          <div class="stats-grid">
            <div class="stat-item">
              <div class="stat-label">Planned Serving Today</div>
              <div class="stat-val">${planned.grams}g <span class="stat-sub">(${planned.portions}p)</span></div>
            </div>
            <div class="stat-item">
              <div class="stat-label">Next Scheduled Meal</div>
              <div class="stat-val" title="${nextMealDisplay}">${nextMealDisplay}</div>
            </div>
            <div class="stat-item">
              <div class="stat-label">Last Eaten</div>
              <div class="stat-val" title="${lastEatDisplay}">${lastEatDisplay}</div>
            </div>
            <div class="stat-item">
              <div class="stat-label">Total Eaten Today</div>
              <div class="stat-val">${eatenToday}g</div>
            </div>
          </div>
        </div>

        <!-- Quick Feed Bar -->
        ${
          this._config.show_quick_feed
            ? `
          <div class="quick-feed-bar">
            <div class="stepper">
              <button class="stepper-btn" id="sub-portion">-</button>
              <div class="stepper-label">
                ${this._manualPortions} portion${this._manualPortions > 1 ? "s" : ""}<br>
                <small style="color:var(--pawsync-secondary-text); font-weight:normal;">~${(this._manualPortions * density).toFixed(0)}g</small>
              </div>
              <button class="stepper-btn" id="add-portion">+</button>
            </div>
            <div style="display:flex; gap:6px;">
              <button class="tare-btn" id="tare-btn" title="Zero Bowl Scale">Tare</button>
              <button class="feed-btn" id="feed-now-btn">
                <span>🍖</span> Feed
              </button>
            </div>
          </div>
        `
            : ""
        }

        <!-- Collapsible Feeding Schedule Section -->
        ${
          this._config.show_schedule
            ? `
          <div class="schedule-header" id="schedule-header">
            <div class="schedule-title">
              <span>📅</span> Feeding Schedule
            </div>
            <div class="schedule-header-right">
              <div class="active-badge">${activeMealsCount} active meal${activeMealsCount === 1 ? "" : "s"}</div>
              <span class="chevron-icon ${this._scheduleCollapsed ? "" : "expanded"}">▶</span>
            </div>
          </div>

          <div class="schedule-body ${this._scheduleCollapsed ? "collapsed" : ""}">
            <div class="meal-list">
              ${schedules
                .map((m, idx) => {
                  const daysMask = this._getDaysMask(m.days);
                  const mealGrams = (m.portions * density).toFixed(0);
                  return `
                  <div class="meal-card ${m.enabled ? "" : "disabled"}">
                    <div class="meal-left" data-edit-idx="${idx}">
                      <div class="meal-main-row">
                        <span class="meal-time">${m.time}</span>
                        <span class="meal-tag">Meal ${m.meal} · ${m.portions}p (~${mealGrams}g)</span>
                        ${m.sound ? `<span style="font-size:12px;" title="Chime enabled">🔔</span>` : ""}
                      </div>
                      <div class="meal-days-row">
                        <div class="day-pill ${daysMask.su ? "active" : ""}">Su</div>
                        <div class="day-pill ${daysMask.mo ? "active" : ""}">Mo</div>
                        <div class="day-pill ${daysMask.tu ? "active" : ""}">Tu</div>
                        <div class="day-pill ${daysMask.we ? "active" : ""}">We</div>
                        <div class="day-pill ${daysMask.th ? "active" : ""}">Th</div>
                        <div class="day-pill ${daysMask.fr ? "active" : ""}">Fr</div>
                        <div class="day-pill ${daysMask.sa ? "active" : ""}">Sa</div>
                      </div>
                    </div>
                    <div class="meal-right">
                      <label class="switch">
                        <input type="checkbox" ${m.enabled ? "checked" : ""} data-toggle-idx="${idx}">
                        <span class="slider"></span>
                      </label>
                      <button class="edit-icon-btn" data-edit-idx="${idx}" title="Edit Schedule">✎</button>
                    </div>
                  </div>
                `;
                })
                .join("")}
            </div>

            <button class="add-meal-btn" id="add-meal-btn">
              + Configure Next Meal Slot
            </button>
          </div>
        `
            : ""
        }

        <!-- Interactive Meal Editor Modal Sheet -->
        ${this._editingMeal ? this._renderMealEditor(density) : ""}
      </ha-card>
    `;

    this._bindEvents();
  }

  _renderMealEditor(density) {
    const meal = this._editingMeal;
    const daysMask = this._getDaysMask(meal.days);
    const mealEstGrams = (meal.portions * density).toFixed(0);

    return `
      <div class="modal-overlay" id="modal-overlay">
        <div class="modal-card">
          <div class="modal-header">
            <div class="modal-title">Edit Scheduled Meal #${meal.meal}</div>
            <button class="modal-close" id="modal-close">✕</button>
          </div>

          <!-- Time Picker -->
          <div class="modal-field">
            <div class="field-label">Feeding Time (24h)</div>
            <div class="time-picker-row">
              <input type="time" class="time-input" id="edit-time" value="${meal.time}">
            </div>
          </div>

          <!-- Repeat Days -->
          <div class="modal-field">
            <div class="field-label">Repeat Days</div>
            <div class="day-selector-pills">
              <button class="day-sel-btn ${daysMask.su ? "active" : ""}" data-day="su">Su</button>
              <button class="day-sel-btn ${daysMask.mo ? "active" : ""}" data-day="mo">Mo</button>
              <button class="day-sel-btn ${daysMask.tu ? "active" : ""}" data-day="tu">Tu</button>
              <button class="day-sel-btn ${daysMask.we ? "active" : ""}" data-day="we">We</button>
              <button class="day-sel-btn ${daysMask.th ? "active" : ""}" data-day="th">Th</button>
              <button class="day-sel-btn ${daysMask.fr ? "active" : ""}" data-day="fr">Fr</button>
              <button class="day-sel-btn ${daysMask.sa ? "active" : ""}" data-day="sa">Sa</button>
            </div>
            <div class="day-presets">
              <button class="preset-chip" id="preset-all">Every day</button>
              <button class="preset-chip" id="preset-weekdays">Weekdays</button>
              <button class="preset-chip" id="preset-weekends">Weekends</button>
            </div>
          </div>

          <!-- Portions Stepper -->
          <div class="modal-field">
            <div class="field-label">Portions Count (Calibrated: ${density}g/portion)</div>
            <div style="display:flex; align-items:center; justify-content:space-between; background:var(--pawsync-surface); border-radius:10px; padding:8px 14px;">
              <button class="stepper-btn" id="modal-sub-portion">-</button>
              <div style="text-align:center;">
                <span style="font-size:16px; font-weight:700;" id="modal-portions-label">${meal.portions} portion${meal.portions > 1 ? "s" : ""}</span>
                <div style="font-size:11px; color:var(--pawsync-secondary-text);">~${mealEstGrams}g</div>
              </div>
              <button class="stepper-btn" id="modal-add-portion">+</button>
            </div>
          </div>

          <!-- Sound Chime Toggle -->
          <div class="modal-field">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <div>
                <div style="font-size:13px; font-weight:700; color:var(--pawsync-text);">Dispense Chime</div>
                <div style="font-size:11px; color:var(--pawsync-secondary-text);">Play sound when dispensing kibble</div>
              </div>
              <label class="switch">
                <input type="checkbox" id="edit-sound" ${meal.sound ? "checked" : ""}>
                <span class="slider"></span>
              </label>
            </div>
          </div>

          <!-- Action Buttons -->
          <div class="modal-actions">
            <button class="modal-btn danger" id="modal-disable-btn">Disable Meal</button>
            <button class="modal-btn secondary" id="modal-cancel-btn">Cancel</button>
            <button class="modal-btn primary" id="modal-save-btn">Save Schedule</button>
          </div>
        </div>
      </div>
    `;
  }

  _getDaysMask(daysStr) {
    const s = (daysStr || "all").toLowerCase();
    if (s === "all" || s === "daily" || s === "everyday" || s === "127") {
      return { su: true, mo: true, tu: true, we: true, th: true, fr: true, sa: true };
    }
    if (s === "weekdays" || s === "workdays" || s === "62") {
      return { su: false, mo: true, tu: true, we: true, th: true, fr: true, sa: false };
    }
    if (s === "weekends" || s === "65") {
      return { su: true, mo: false, tu: false, we: false, th: false, fr: false, sa: true };
    }
    return {
      su: s.includes("su"),
      mo: s.includes("mo"),
      tu: s.includes("tu"),
      we: s.includes("we"),
      th: s.includes("th"),
      fr: s.includes("fr"),
      sa: s.includes("sa"),
    };
  }

  _formatDaysString(mask) {
    if (mask.su && mask.mo && mask.tu && mask.we && mask.th && mask.fr && mask.sa) {
      return "All";
    }
    if (!mask.su && mask.mo && mask.tu && mask.we && mask.th && mask.fr && !mask.sa) {
      return "Weekdays";
    }
    if (mask.su && !mask.mo && !mask.tu && !mask.we && !mask.th && !mask.fr && mask.sa) {
      return "Weekends";
    }
    const days = [];
    if (mask.su) days.push("Su");
    if (mask.mo) days.push("Mo");
    if (mask.tu) days.push("Tu");
    if (mask.we) days.push("We");
    if (mask.th) days.push("Th");
    if (mask.fr) days.push("Fr");
    if (mask.sa) days.push("Sa");
    return days.join(",");
  }

  _bindEvents() {
    // Multi-feeder tabs
    this.shadowRoot.querySelectorAll(".feeder-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        this._selectedFeederIdx = parseInt(tab.dataset.idx, 10);
        this._render();
      });
    });

    // Toggle collapsible Feeding Schedule header
    const scheduleHeader = this.shadowRoot.getElementById("schedule-header");
    if (scheduleHeader) {
      scheduleHeader.addEventListener("click", () => {
        this._scheduleCollapsed = !this._scheduleCollapsed;
        this._render();
      });
    }

    // Quick portion stepper
    const subBtn = this.shadowRoot.getElementById("sub-portion");
    const addBtn = this.shadowRoot.getElementById("add-portion");
    if (subBtn) {
      subBtn.addEventListener("click", () => {
        if (this._manualPortions > 1) {
          this._manualPortions--;
          this._render();
        }
      });
    }
    if (addBtn) {
      addBtn.addEventListener("click", () => {
        if (this._manualPortions < 20) {
          this._manualPortions++;
          this._render();
        }
      });
    }

    // Quick feed button
    const feedBtn = this.shadowRoot.getElementById("feed-now-btn");
    if (feedBtn) {
      feedBtn.addEventListener("click", () => this._feed(this._manualPortions));
    }

    // Tare button
    const tareBtn = this.shadowRoot.getElementById("tare-btn");
    if (tareBtn) {
      tareBtn.addEventListener("click", () => this._tare());
    }

    // Meal toggle switches
    this.shadowRoot.querySelectorAll("input[data-toggle-idx]").forEach((chk) => {
      chk.addEventListener("change", (e) => {
        const idx = parseInt(e.target.dataset.toggleIdx, 10);
        this._toggleMeal(idx, e.target.checked);
      });
    });

    // Meal edit triggers
    this.shadowRoot.querySelectorAll("[data-edit-idx]").forEach((el) => {
      el.addEventListener("click", (e) => {
        if (e.target.tagName.toLowerCase() === "input") return;
        const idx = parseInt(el.dataset.editIdx, 10);
        const feeder = this._getActiveFeeder();
        const meal = this._localSchedules[feeder.prefix][idx];
        this._editingMeal = { ...meal };
        this._render();
      });
    });

    // Add meal button
    const addMealBtn = this.shadowRoot.getElementById("add-meal-btn");
    if (addMealBtn) {
      addMealBtn.addEventListener("click", () => {
        const feeder = this._getActiveFeeder();
        const schedules = this._localSchedules[feeder.prefix];
        const nextIdx = schedules.findIndex((m) => !m.enabled);
        const targetIdx = nextIdx >= 0 ? nextIdx : 0;
        this._editingMeal = {
          ...schedules[targetIdx],
          enabled: true,
        };
        this._render();
      });
    }

    // Modal Events
    if (this._editingMeal) {
      const closeBtn = this.shadowRoot.getElementById("modal-close");
      const cancelBtn = this.shadowRoot.getElementById("modal-cancel-btn");
      const saveBtn = this.shadowRoot.getElementById("modal-save-btn");
      const disableBtn = this.shadowRoot.getElementById("modal-disable-btn");
      const overlay = this.shadowRoot.getElementById("modal-overlay");

      const closeModal = () => {
        this._editingMeal = null;
        this._render();
      };

      if (closeBtn) closeBtn.addEventListener("click", closeModal);
      if (cancelBtn) cancelBtn.addEventListener("click", closeModal);
      if (overlay) {
        overlay.addEventListener("click", (e) => {
          if (e.target === overlay) closeModal();
        });
      }

      // Modal day pills
      this.shadowRoot.querySelectorAll(".day-sel-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          const day = btn.dataset.day;
          const mask = this._getDaysMask(this._editingMeal.days);
          mask[day] = !mask[day];
          this._editingMeal.days = this._formatDaysString(mask);
          this._render();
        });
      });

      // Presets
      const presetAll = this.shadowRoot.getElementById("preset-all");
      const presetWeekdays = this.shadowRoot.getElementById("preset-weekdays");
      const presetWeekends = this.shadowRoot.getElementById("preset-weekends");

      if (presetAll) {
        presetAll.addEventListener("click", () => {
          this._editingMeal.days = "All";
          this._render();
        });
      }
      if (presetWeekdays) {
        presetWeekdays.addEventListener("click", () => {
          this._editingMeal.days = "Weekdays";
          this._render();
        });
      }
      if (presetWeekends) {
        presetWeekends.addEventListener("click", () => {
          this._editingMeal.days = "Weekends";
          this._render();
        });
      }

      // Modal portion stepper
      const modalSub = this.shadowRoot.getElementById("modal-sub-portion");
      const modalAdd = this.shadowRoot.getElementById("modal-add-portion");
      if (modalSub) {
        modalSub.addEventListener("click", () => {
          if (this._editingMeal.portions > 1) {
            this._editingMeal.portions--;
            this._render();
          }
        });
      }
      if (modalAdd) {
        modalAdd.addEventListener("click", () => {
          if (this._editingMeal.portions < 20) {
            this._editingMeal.portions++;
            this._render();
          }
        });
      }

      // Save button
      if (saveBtn) {
        saveBtn.addEventListener("click", () => {
          const timeInput = this.shadowRoot.getElementById("edit-time");
          const soundInput = this.shadowRoot.getElementById("edit-sound");
          this._editingMeal.time = timeInput ? timeInput.value : this._editingMeal.time;
          this._editingMeal.sound = soundInput ? soundInput.checked : true;
          this._editingMeal.enabled = true;
          this._saveMealEditor(this._editingMeal);
        });
      }

      // Disable button
      if (disableBtn) {
        disableBtn.addEventListener("click", () => {
          this._editingMeal.enabled = false;
          this._saveMealEditor(this._editingMeal);
        });
      }
    }
  }
}

/**
 * Visual GUI Editor for Lovelace Dashboard configuration
 */
class PawsyncFeederCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this.render();
  }

  set hass(hass) {
    this._hass = hass;
    this.render();
  }

  render() {
    if (!this._hass) return;
    const config = this._config || {};
    this.innerHTML = `
      <div style="display:flex; flex-direction:column; gap:12px; padding:12px 0;">
        <div>
          <label style="font-weight:600; font-size:13px; display:block; margin-bottom:4px;">Card Title</label>
          <input type="text" id="title" value="${config.title || "Pet Feeder"}" 
            style="width:100%; padding:8px; border-radius:6px; border:1px solid #ccc; box-sizing:border-box;">
        </div>

        <div>
          <label style="font-weight:600; font-size:13px; display:block; margin-bottom:4px;">Feeder Device Prefix (optional, leave blank for auto-detect)</label>
          <input type="text" id="feeder_prefix" value="${config.feeder_prefix || ""}" placeholder="e.g. pawsync_ppf_r361s_feeder"
            style="width:100%; padding:8px; border-radius:6px; border:1px solid #ccc; box-sizing:border-box;">
        </div>

        <div>
          <label style="font-weight:600; font-size:13px; display:block; margin-bottom:4px;">Kibble Density (Grams per portion fallback)</label>
          <input type="number" id="grams_per_portion" step="0.1" value="${config.grams_per_portion || 9.0}" 
            style="width:100%; padding:8px; border-radius:6px; border:1px solid #ccc; box-sizing:border-box;">
        </div>

        <div style="display:flex; align-items:center; gap:8px;">
          <input type="checkbox" id="default_collapsed" ${config.default_collapsed !== false ? "checked" : ""}>
          <label for="default_collapsed" style="font-weight:600; font-size:13px;">Default Feeding Schedule to Collapsed</label>
        </div>
      </div>
    `;

    const titleInput = this.querySelector("#title");
    const prefixInput = this.querySelector("#feeder_prefix");
    const gramsInput = this.querySelector("#grams_per_portion");
    const collapsedInput = this.querySelector("#default_collapsed");

    const updateConfig = () => {
      const newConfig = {
        ...(this._config || {}),
        title: titleInput ? titleInput.value : "Pet Feeder",
        feeder_prefix: prefixInput && prefixInput.value ? prefixInput.value.trim() : undefined,
        grams_per_portion: gramsInput ? parseFloat(gramsInput.value) || 9.0 : 9.0,
        default_collapsed: collapsedInput ? collapsedInput.checked : true,
      };
      const event = new CustomEvent("config-changed", {
        detail: { config: newConfig },
        bubbles: true,
        composed: true,
      });
      this.dispatchEvent(event);
    };

    if (titleInput) titleInput.addEventListener("change", updateConfig);
    if (prefixInput) prefixInput.addEventListener("change", updateConfig);
    if (gramsInput) gramsInput.addEventListener("change", updateConfig);
    if (collapsedInput) collapsedInput.addEventListener("change", updateConfig);
  }
}

if (!customElements.get("pawsync-feeder-card")) {
  customElements.define("pawsync-feeder-card", PawsyncFeederCard);
}
if (!customElements.get("pawsync-feeder-card-editor")) {
  customElements.define("pawsync-feeder-card-editor", PawsyncFeederCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "pawsync-feeder-card")) {
  window.customCards.push({
    type: "pawsync-feeder-card",
    name: "Pawsync Feeder Card",
    preview: true,
    description: "Interactive smart pet feeder card replicating the Pawsync app experience with graphical meal scheduling and multi-feeder support.",
  });
}
