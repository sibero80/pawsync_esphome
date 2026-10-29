# 🐾 PawSync: 100% Local, Cloud-Free Control for Pawsync / VeSync Smart Pet Feeders (Zero-Teardown OTA, Live Scale, Lovelace Card)

**Category:** *Share Your Projects! / Custom Integrations*  
**Tags:** *esphome, custom-components, pet-feeder, pawsync, hacs, zero-cloud*

---

Hey everyone! 👋

I'm excited to share a project I've been working on: **[PawSync for Home Assistant](https://github.com/sibero80/pawsync_esphome)**.

If you own a **Pawsync Smart Pet Feeder (Model PPF-R361S)** (part of the VeSync / Levoit / Etekcity ecosystem) and were frustrated by cloud dependency, delayed app notifications, or the risk of cloud outages leaving your pets unfed, this integration is for you.

We completely reverse-engineered the feeder's internal hardware (ESP32-C3 + Sinowealth motor/scale coprocessor) and built a **100% local, native ESPHome integration** with a **zero-teardown wireless onboarding wizard** right inside Home Assistant.

---

### ✨ What Makes This Special?

1. **Zero-Teardown Wireless Flashing**:
   - No screwdrivers, no soldering, no UART cables.
   - Home Assistant discovers your feeder via your VeSync account, bypasses the stock cloud, and flashes custom ESPHome firmware over your local Wi-Fi in ~60 seconds using an embedded HTTP stager.

2. **1-Click Factory Stock Rollback Safety**:
   - We believe in zero-risk IoT hacking. During conversion, the feeder automatically streams a full factory backup (`stock_firmware.bin` and calibration data) directly to your Home Assistant host.
   - Want to return the feeder to the genuine VeSync app? Just call `pawsync.restore_stock_firmware` with 1 click in Home Assistant, and it flashes right back over Wi-Fi!

3. **Official App-Replica Lovelace Card (Bundled)**:
   - Includes an authentic, interactive card that automatically registers in Lovelace—no manual JS installation needed.
   - Live stainless steel bowl scale filling dynamically with kibble.
   - Pulsing glow indicator when your pet is actively eating.
   - Real-time eating speed telemetry (`g/min`), last eaten timestamps, and daily consumption tracking.
   - Collapsible 7-plan feeding schedule manager with visual meal pickers.

4. **100% Native Alert Parity Blueprint**:
   - Includes a ready-to-use notification blueprint ([`pawsync_notifications.yaml`](https://github.com/sibero80/pawsync_esphome/blob/main/blueprints/automation/pawsync_notifications.yaml)) covering all 14 official mobile app channels: motor jams, food empty/low warnings, bowl removal detection, overflow safety (>150g), eating speed alerts, and 30-day chute cleaning reminders.

5. **Multi-Feeder & Hardened Security**:
   - Each feeder is isolated with its own unique cryptographic Noise PSK encryption key, unique Port 3232 OTA password, and permissions-locked credentials.
   - Routine firmware upgrades are handled right from your Home Assistant update entity with live progress bars.

---

### 🚀 Quick Start (HACS)

1. Open **HACS** → **Integrations** → **Custom repositories** (three dots top right).
2. Add:
   ```text
   https://github.com/sibero80/pawsync_esphome
   ```
   Category: **Integration**
3. Click **Download**, then restart Home Assistant.
4. Go to **Settings** → **Devices & Services** → **Add Integration** → search for **PawSync**.
5. Follow the step-by-step onboarding wizard!

---

### 🐾 Support Matruska Cat Shelter (Medellín)

Instead of buying me a coffee, please consider donating a dollar to **[Matruska Cat Shelter](https://matruska.co)** ([PayPal Donation Link](https://www.paypal.com/ncp/payment/KMWR984RL7M6G)), a grassroots non-profit rescue in Medellín, Colombia, dedicated to rehabilitating sick, disabled, and bottle-fed newborn kittens.

---

### 🔗 Repositories & Resources

- **Home Assistant Integration & ESPHome**: [github.com/sibero80/pawsync_esphome](https://github.com/sibero80/pawsync_esphome)
- **Standalone OTA Compiler & Forensic Toolkit**: [github.com/sibero80/pawsync_ota](https://github.com/sibero80/pawsync_ota)
- **Step-by-Step Onboarding Guide**: [ONBOARDING_GUIDE.md](https://github.com/sibero80/pawsync_esphome/blob/main/ONBOARDING_GUIDE.md)
- **Stock Rollback Runbook**: [STOCK_ROLLBACK_AND_RECOVERY.md](https://github.com/sibero80/pawsync_esphome/blob/main/STOCK_ROLLBACK_AND_RECOVERY.md)

Feedback, issues, and pull requests are always welcome! Let me know how it works for your pets! 🐶🐱
