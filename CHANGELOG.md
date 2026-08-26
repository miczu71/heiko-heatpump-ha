# Changelog

All notable changes to this project are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.8.5] - 2026-08-26

### Fixed
- The 1.8.4 fix for raw options-dialog labels targeted the wrong file: `strings.json` is only read by the upstream hassfest/Lokalise translation pipeline for core integrations and is never loaded at runtime for a custom integration like this one. HA actually reads `translations/en.json`, which had no `config` section at all (only `issues`) — meaning the **initial setup form** has been showing raw field keys (`host`, `port`, `mn`, `flow_rate_lps`) since day one, not just the options/reconfigure dialog. Verified empirically via Playwright against the live UI before and after this fix. Both `config` and `options` sections are now mirrored into `translations/en.json`

## [1.8.4] - 2026-08-26

### Removed (dead code, no behavior change)
- `coordinator.py`: 7 unused imports (`asyncio`, `typing.Any`, `MODE_STANDBY`/`MODE_HEATING`/`MODE_COOLING`/`MODE_DHW`/`MODE_AUTO`), the unused `self._mn_config` field, and `async_set_setpoint()` — no entity or service ever called it (the heating setpoint is controlled via the heating curve, not a direct setpoint write)
- `sensor.py`: unused `logging` import and `_LOGGER`

### Changed (internal refactor — no behavior change)
- Finished the `HeikoBaseEntity` migration started in 1.8.0: `sensor.py` (6 classes) and `select.py` (1 class) now use the shared base class instead of hand-rolling an identical `DeviceInfo` block each. `unique_id` values are unchanged — no entity re-registration
- Removed 7 `_handle_coordinator_update` overrides (`sensor.py` ×6, `water_heater.py` ×1) that were byte-identical to `CoordinatorEntity`'s default implementation

### Fixed
- Options flow (reconfigure existing entry) now shows proper field labels instead of raw keys (`host`, `port`, `mn`, `flow_rate_lps`) — `strings.json` was missing an `options` section
- Write-command failures now raise `HomeAssistantError` instead of a bare `RuntimeError`, so the UI shows a clean error instead of a traceback
- `config_flow.py`: narrowed `except (ValueError, Exception)` to `except ValueError` in two places — the bare `Exception` catch was silently swallowing real bugs

## [1.8.3] - 2026-08-26

### Added
- **`async_remove_config_entry_device`** — the integration previously had no removal hook, so Home Assistant unconditionally refused to delete any device under this config entry (UI trash icon and the device-registry API both failed with "Config entry does not support device removal"). This blocked cleanup of stale/orphaned registry entries left over from earlier versions that keyed device identifiers by config-entry ID instead of MAC. Now returns `True` unconditionally — there is exactly one physical device per entry, so any device registered under it that Home Assistant offers for removal is safe to delete

## [1.8.2] - 2026-05-15

### Fixed / Performance
- **Realtime change detection** — `_handle_realtime` now compares the new parameter dict to the previous one before calling `async_set_updated_data`; entities are not notified when the pump sends identical readings (common in standby). Cuts per-frame entity callbacks by up to 3–5× in stable operating conditions
- **Skip redundant poll** — `_async_update_data` skips the CMD 0x06 active poll if the pump pushed data within the last 60 s (same as `POLL_INTERVAL`); halves wire traffic under normal conditions
- **`FrameBuffer` O(n²) → O(n)** — replaced `bytearray.pop(0)` loop (O(n²) on garbage input) with `bytearray.find()` + `del buf[:idx]` (O(n)); added 8 KiB cap on buffer growth when no valid header is found, preventing unbounded memory use on a misbehaving bridge
- **Stale HBH write-index comment** — `build_set_hbh` docstring and `async_set_hbh` docstring both said "Write index 48" but `WRITE_IDX_HBH = 50` has always been correct; comments updated

## [1.8.1] - 2026-05-15

### Changed (internal refactor — no behavior change)
- **`_SETDATA_MAP` table** in `coordinator.py` — replaces 18 hand-coded `_read_float` + store blocks (~115 lines) with a 24-entry declarative table and a single loop; also detects which keys actually changed before calling `async_set_updated_data`, so entities are not notified when the pump sends the same setdata twice
- **`_SETDATA_KEYS` frozenset** derived automatically from the map — replaces the hand-maintained 24-key preserved-keys tuple in `_handle_realtime`; adding a new setdata field now requires only one table entry
- **Collapsed 10 per-point coordinator methods** — `async_set_curve_amb_{1..5}` and `async_set_curve_water_{1..5}` replaced by `async_set_curve_amb(point, value)` and `async_set_curve_water(point, value)`; `number.py` lambdas and `__init__.py` service handlers updated to call the new signatures directly (no more `getattr`)
- **Repair issue transition gating** — `async_create_issue` is now called only on the fresh→stale transition (not every poll) and `async_delete_issue` only on stale→fresh; eliminates issue-registry churn visible in logs
- **Stale-issue ordering** — connectivity is checked before stale-age, so a disconnected pump does not raise the stale-data repair issue
- **Debug-log guard** on `_LOGGER.debug("Received realtime data: %s", params)` — avoids building the dict string every 30 s when debug logging is off
- **`import struct` moved to module level** from inside `_handle_setdata` hot path
- **`__init__.py` platforms docstring** corrected (previously listed non-existent "climate" platform)

## [1.8.0] - 2026-05-15

### Changed (internal refactor — no behavior change)
- **New `entity.py` base class** — `HeikoBaseEntity` centralises `unique_id` and `DeviceInfo` setup; eliminates 8 identical `DeviceInfo(identifiers=…)` blocks spread across entity platforms
- **Description-based number entities** — `HeikoNumberEntityDescription` frozen dataclass replaces the 12-argument `HeikoNumberEntity` constructor; write callables stored directly instead of method-name strings dispatched via `getattr`
- **Description-based switch entities** — `HeikoSwitchEntityDescription` frozen dataclass replaces `_SWITCH_DEFS` positional tuples and `getattr` write dispatch in `switch.py`
- **`select.py` mode compare** — `if option == "Standby":` replaced with `if mode_val == MODE_STANDBY:` to decouple behaviour from the UI label string
- **`except Exception` → `_LOGGER.exception`** — `select.py` (and `number.py`, `switch.py`) now log full stack traces on write errors instead of swallowing them with `.error(…, exc)`

## [1.7.4] - 2026-04-27

### Fixed
- **Number card shows integer values** — `native_value` now returns `int` when `step=1`, so HA stores e.g. `-13` instead of `-13.0` in the state machine; the device card no longer renders `-13,0 °C`

## [1.7.2] - 2026-04-23

### Changed
- All editable number entities now use step 1 — values display as integers (e.g. `6 °C` instead of `6.0 °C`). Affected: DHW Setpoint, Heating/Cooling Stops ΔT, Heating/Cooling Restarts ΔT, DHW Restart ΔT, HC Amb 1–5, HC Water 1–5

## [1.7.3] - 2026-04-26

### Fixed
- **Spurious CRC mismatch warning** — CMD 0x02 setdata frames logged a `CRC mismatch` warning on every poll because the code applied the CMD 0x01 XOR offset (0x0903) to all unit→server frames. CMD 0x02 uses a different offset (0x0DB0). `parse_frame()` now selects the correct offset by command byte; both frame types verify cleanly

## [1.7.1] - 2026-04-23

### Changed
- Heating curve number entities renamed for readability in the device card (names were truncated before the point number was visible):
  - `Heating Curve Parallel Shift` → `HC Parallel`
  - `Curve Ambient Temp 1–5` → `HC Amb 1–5`
  - `Curve Water Temp 1–5` → `HC Water 1–5`

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
