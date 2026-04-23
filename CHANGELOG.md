# Changelog

All notable changes to this project are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.7.0] - 2026-04-23

### Added

- **Anti-Legionella switch** — `switch.anti_legionella_program` — enables/disables the legionella protection programme (write index 40; confirmed by CMD 0x05 MITM capture)
- **3 Anti-Legionella number entities** — all values read live from CMD 0x02 setdata; show `unavailable` until first setdata frame (~3 min):

  | Entity | Write index | Range | Description |
  |--------|-------------|-------|-------------|
  | Anti-Legionella Setpoint | 41 | 40–70 °C | Temperature the water must reach during the cycle |
  | Anti-Legionella Duration | 42 | 1–120 min | How long the pump holds the setpoint |
  | Anti-Legionella Finish Time | 43 | 1–240 min | Cycle finish/timeout time |

- **Anti-Legionella Running binary sensor** — `binary_sensor.anti_legionella_running` — `ON` when the programme is enabled (Anti_Leg_Program = 1) and the pump is in DHW mode (WorkingMode = 1), which is the observable state change when the legionella cycle fires
- **4 new HA services**:

  | Service | Parameters | Description |
  |---------|-----------|-------------|
  | `heiko_heatpump.set_anti_leg_program` | `enabled` (true/false) | Enable/disable the programme |
  | `heiko_heatpump.set_anti_leg_setpoint` | `temperature` (40–70 °C) | Set legionella kill temperature |
  | `heiko_heatpump.set_anti_leg_duration` | `minutes` (1–120) | Set hold duration |
  | `heiko_heatpump.set_anti_leg_finish` | `minutes` (1–240) | Set cycle finish time |

### Notes

- Write indices 40–43 confirmed by CMD 0x05 MITM capture of cloud→pump traffic; setdata baseline confirmed live values (setpoint 70°C, duration 20 min, finish time 120 min)
- The **day/hour schedule** for the legionella cycle is stored in the WinCE panel's firmware only and is not accessible via the RS-485 protocol. It cannot be read or written by this integration
- The Running sensor cannot distinguish between a legionella cycle and a user-initiated DHW session; both produce WorkingMode = 1

## [1.6.0] - 2026-04-23

### Added
- **14 number entities** — all values read live from the pump (CMD 0x02 setdata frames, never hardcoded):
  - **Heating Curve Parallel Shift** (write index 120, −9…+9 °C) — shifts the entire weather-compensated curve up or down
  - **Heating/Cooling Stops ΔT** (write index 19, 1–15 °C) — water ΔT above setpoint at which heating/cooling stops
  - **Heating/Cooling Restarts ΔT** (write index 20, 1–15 °C) — water ΔT below setpoint at which heating/cooling restarts
  - **DHW Restart ΔT** (write index 55, 1–15 °C) — DHW temperature drop that triggers reheating
  - **Curve Ambient Temp 1–5** (write indices 24–28, −25…+20 °C) — heating curve ambient temperature breakpoints
  - **Curve Water Temp 1–5** (write indices 29–33, 15–60 °C) — heating curve target water temperature breakpoints
- **6 new HA services**:
  - `heiko_heatpump.set_curve_parallel` — parallel-shift the heating curve (`shift` −9…+9)
  - `heiko_heatpump.set_heating_stops_delta` — set heating/cooling stop ΔT (`delta` 1–15 °C)
  - `heiko_heatpump.set_heating_restarts_delta` — set heating/cooling restart ΔT (`delta` 1–15 °C)
  - `heiko_heatpump.set_dhw_restart_delta` — set DHW restart ΔT (`delta` 1–15 °C)
  - `heiko_heatpump.set_curve_ambient_temp` — set one ambient breakpoint (`point` 1–5, `temperature` −25…+20 °C)
  - `heiko_heatpump.set_curve_water_temp` — set one water-temp breakpoint (`point` 1–5, `temperature` 15–60 °C)

All write indices confirmed by MITM capture of live cloud→pump traffic.

## [1.5.2] - 2026-04-22

### Changed
- Connection binary sensor moved to **diagnostic entity category** — no longer appears in the main entity list; accessible via Settings → Entities

## [1.5.1] - 2026-04-21

### Fixed
- **Binary sensor showed as "Unnamed device"** — was using the config entry ID as device identifier instead of the pump's MN; now correctly joins the main Heiko Heat Pump device
- **COP estimate produced absurd values (~36×) in DHW mode** — Tw and Tc are from different hydraulic circuits during DHW operation (ΔT can reach 30–40 °C); COP is now only computed when `0.5 < Tw − Tc ≤ 15 °C`

## [1.5.0] - 2026-04-20

### Added
- **HA Repairs alert** — raises a repair issue in Settings → Repairs if the pump stops sending data for 5+ minutes, showing elapsed time and last-seen timestamp; clears automatically when data resumes

## [1.4.0] - 2026-04-20

### Removed
- **Climate entity** — removed and fully replaced by the water heater entity (introduced in v1.3.0)

## [1.3.0] - 2026-04-20

### Added
- **Water Heater entity** — shows current DHW temperature, target setpoint (40–60 °C), and operation mode; controls DHW setpoint directly
- **Diagnostics download** — download all current sensor values as redacted JSON from the device page (host and MN replaced with placeholders)
- **Working-time duration sensors** — AH, HBH, and HWTBH accumulated run-time counters in minutes
- Technical sensors (EEV, PWM, fan speeds, refrigerant temperatures) now **disabled by default** — enable individually in Settings → Entities if needed

## [1.2.0] - 2026-04-20

### Added
- **Last Seen sensor** (diagnostic) — timestamp of the last frame received from the pump
- **Reconnect Count sensor** (diagnostic) — TCP reconnection counter since HA started
- **6 HA services** callable from automations or Developer Tools → Services:
  - `heiko_heatpump.set_dhw_setpoint` — set DHW target temperature (40–60 °C)
  - `heiko_heatpump.set_mode` — set working mode (standby / heating / cooling / dhw / auto)
  - `heiko_heatpump.set_power` — turn pump on or off
  - `heiko_heatpump.set_heating_curve` — enable/disable weather-compensated curve
  - `heiko_heatpump.set_hbh` — enable/disable backup heater
  - `heiko_heatpump.set_dhw_storage` — enable/disable DHW storage mode
- **Options flow** — edit host, port, MN, and flow rate after setup via Settings → Devices & Services → Configure without re-adding the integration

## [1.1.0] - 2026-04-20

### Added
- **Connection binary sensor** — `binary_sensor.heiko_heat_pump_connection` (device class: connectivity, diagnostic category) — shows live TCP socket status; goes `OFF` within seconds of losing the bridge

## [1.0.0] - 2026-04-20

### Added
- Initial release
- Local push integration via USR-W600 TCP bridge — no cloud dependency
- Climate entity with DHW setpoint control and working-mode presets
- 4 switches: Power, Heating Curve, Backup Heater (HBH), DHW Storage
- 30+ sensor entities: temperatures, pressures, compressor frequency, electrical, COP estimates
- All write commands verified by MITM capture of live cloud→pump traffic
