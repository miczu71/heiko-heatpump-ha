# Heiko Heat Pump — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/v/release/miczu71/heiko-heatpump-ha)](https://github.com/miczu71/heiko-heatpump-ha/releases)

Local-only (no cloud) Home Assistant custom integration for **Heiko / Neoheat / ECOtouch** heat pumps connected via a **USR-W600 WiFi-to-RS-485 bridge**.

## How it works

The USR-W600 acts as a transparent TCP server on port 8899. The heat pump pushes two kinds of binary frames:

- **CMD 0x01 realtime** (~every 30 s) — temperatures, pressures, compressor, electrical values, working-time counters.
- **CMD 0x02 setdata** (~every 3 min) — all pump *settings* (138 float slots).

This integration connects as a TCP client, parses the frames, and exposes the values as HA entities. It also polls every 60 s as a fallback and writes settings back with CMD 0x05.

Write indices were confirmed either by MITM-capturing live cloud→pump traffic, by a real write followed by a read-back from the pump's own frame, or by an isolated single-field change on the physical panel (see [How the registers were mapped](#how-the-registers-were-mapped)). Setting entities have no value until the first setdata frame arrives (up to ~3 minutes after connection).

## Features

- **1 water heater entity** — DHW setpoint (40–60 °C), current water temperature, operation mode
- **9 switches** — power, heating curve, DHW storage, Anti-Legionella, Vacation Mode, backup-source presence (heating / DHW), reduced setpoint, plus a legacy alias of the DHW backup-heater priority
- **7 selects** — working mode, circulation pump P0 (type, mode, speed in heating / DHW), priority of the additional heat source vs the internal heater AH (heating / DHW)
- **24 number entities** — heating and DHW setpoints, heating-curve shift and all 10 curve breakpoints, hysteresis ΔT settings, Anti-Legionella, circulation pump P0 timing, reduced-setpoint drop, backup-source start delay/dependency
- **15 binary sensors** — TCP connection, Anti-Legionella running, circuit 2 and lock/timer states (most disabled by default)
- **59 sensors** — temperatures, pressures, compressor, electrical power, thermal power, COP estimate, working-time counters and 35 more parameters that are disabled by default
- **26 HA services** — control every writable parameter from automations
- **Repairs alert** — raises an issue in Settings → Repairs if the pump stops sending data for 5+ minutes; clears automatically on recovery
- **Diagnostics** — download all sensor values plus the raw slot tables (`all_floats_realtime`, `all_floats_setdata`, raw hex) as JSON from the device page (host/MN redacted)
- **Slot logging** — optional `debug_slot_logging` option logs every changed slot at INFO level (handy when mapping a new parameter)
- **Options flow** — edit host, port, MN, flow rate and slot logging after setup
- **Local push** — entities update within seconds of each pump frame; exponential-backoff TCP reconnect
- **No cloud required** — all communication is direct TCP to the W600 bridge

## Tested hardware

- Heiko Thermal Plus / Eko II monoblock heat pumps
- USR-W600 WiFi-to-RS-485 bridge (SocketA TCP server mode, port 8899)

Should also work with Neoheat and ECOtouch models using the same USR-W600 bridge.

## Installation

### HACS (recommended)

1. In HACS → **Custom repositories** → add `https://github.com/miczu71/heiko-heatpump-ha` as **Integration**
2. Install **Heiko Heat Pump**
3. Restart Home Assistant
4. **Settings → Devices & Services → Add Integration → Heiko Heat Pump**

### Manual

1. Copy `custom_components/heiko_heatpump/` into your HA `config/custom_components/` folder
2. Restart Home Assistant
3. **Settings → Devices & Services → Add Integration → Heiko Heat Pump**

## Configuration

| Field | Example | Description |
|-------|---------|-------------|
| Bridge IP | `192.168.1.100` | IP address of your USR-W600 |
| Port | `8899` | TCP port (W600 SocketA default) |
| MN | `A1B2C3D4E5F6` | Unit identifier — the W600's WiFi MAC address (no colons), found on the W600 label or in its web UI under **Device Info → MAC** |
| Flow rate | `0.29` | Water flow rate in L/s (used for COP estimation). Eko II 6=0.29, 9=0.43, 12=0.57, 15=0.71, 19=0.92 |
| Slot logging | off | Log every changed setdata/realtime slot at INFO level |

Settings can be changed after setup via **Settings → Devices & Services → Heiko Heat Pump → Configure**.

The MN is used to address CMD 0x05 write frames. The integration also learns the pump's own MN from its first CMD 0x01 frame and uses that for subsequent writes.

## W600 setup

The W600 must be in **SocketA TCP Server** mode:
- Protocol: TCP
- Local port: 8899
- Transfer mode: Transparent

No changes to SocketB are needed for local-only use.

## Entities

Entity IDs are built by HA from the device name and the entity name below. Names here are the entity names as registered by the integration.

### Water Heater
| Entity | Description |
|--------|-------------|
| DHW | Target = DHW setpoint (40–60 °C), current = water outlet temp (Tw), operation mode (Standby / Heating / Cooling / DHW / Auto) |

### Switches

| Entity | Write index | Description |
|--------|-------------|-------------|
| Heat Pump Power | 0 | Power on/off |
| Heating Curve | 23 | Weather-compensated heating curve on/off |
| DHW Storage | 62 | DHW storage mode on/off |
| Anti-Legionella Program | 40 | Enable/disable the legionella protection cycle |
| Vacation Mode | 44 | Vacation mode on/off (the DHW and heating temperature drops are set on the panel; both are 20 °C on the reference installation) |
| Backup Source For Heating | 47 | Declares that an additional heat source (HBH, buffer heater) is installed for space heating — panel: *Dodatkowe źródła ciepła*, row 1 |
| Backup Source For DHW | 49 | Declares that an additional heat source (HWTBH, DHW-tank heater) is installed for DHW — row 3 |
| Reduced Setpoint | 77 | Reduced setpoint on/off — panel: *Ograniczona nastawa → Wartość zadana* (menu 5.1). The drop is set by *Reduced Setpoint Drop/Rise* |
| DHW Backup Priority Lower Than AH | 50 | **Legacy alias of the select *Backup Priority (DHW)*** (see below). Kept with its original entity ID (`…_backup_heater_hbh`) so existing automations keep working. ON = "lower than AH" (AH first). It is **not** an on/off switch for a backup heater |

### Selects

| Entity | Write index | Options | Description |
|--------|-------------|---------|-------------|
| Working Mode | 3 | Standby / Heating / Cooling / DHW / Auto | Direct mode control |
| Backup Priority (Heating) | 48 | Niższe / Wyższe dla grzałki wewnętrznej AH | Priority of the additional source vs AH when assisting heating (panel row 2) |
| Backup Priority (DHW) | 50 | Niższe / Wyższe dla grzałki wewnętrznej AH | Priority of the DHW additional source vs AH (panel row 4) |
| Circulation Pump P0 Type | 86 | Pompa sterowana płynnie / Stałe obroty pompy | Variable (PWM) vs. constant-speed control of the internal circulation pump |
| Circulation Pump P0 Mode | 88 | Domyślny (przerywany) / Pompa włączona na stałe / Praca pompy ze sprężarką | Interval vs. always-on vs. compressor-linked operation |
| Circulation Pump P0 Speed (Heating) | 130 | Wysokie / Średnie / Niskie obroty | Pump speed while in heating mode |
| Circulation Pump P0 Speed (DHW) | 132 | Wysokie / Średnie / Niskie obroty | Pump speed while in DHW mode |

Panel option labels are kept verbatim (Polish) so they match the physical display. The "Domyślny" label for P0 Mode value 0 is a paraphrase — the pump's own panel repeats the field's title there, a firmware bug.

### Numbers

| Entity | Write index | Range | Description |
|--------|-------------|-------|-------------|
| Heating Setpoint | 37 | 15–55 °C | Heating water target **without** curve. Unavailable while the heating curve is on (the pump ignores it then) |
| DHW Setpoint | 54 | 40–60 °C | Domestic hot water target temperature |
| HC Parallel | 120 | −9…+9 °C | Heating curve parallel shift |
| Heating Stops ΔT | 19 | 1–15 °C | Water ΔT above setpoint at which heating/cooling stops |
| Heating Restarts ΔT | 20 | 1–15 °C | Water ΔT below setpoint at which heating/cooling restarts |
| DHW Restart ΔT | 55 | 1–15 °C | DHW temperature drop that triggers reheating |
| HC Amb 1–5 | 24–28 | −25…+20 °C | Ambient temperature breakpoints of the heating curve |
| HC Water 1–5 | 29–33 | 15–60 °C | Target water temperature breakpoints of the heating curve |
| Anti-Legionella Setpoint | 41 | 40–70 °C | Temperature the water must reach during the legionella cycle |
| Anti-Legionella Duration | 42 | 1–120 min | How long the pump holds the setpoint |
| Anti-Legionella Finish Time | 43 | 1–240 min | Cycle finish/timeout time |
| Circulation Pump P0 Run Time | 90 | 1–30 min | Interval-mode run time (installation baseline: 1 min) |
| Circulation Pump P0 Stop Time | 89 | 1–60 min | Interval-mode stop time (installation baseline: 6 min) |
| Reduced Setpoint Drop/Rise | 78 | 2–10 °C | Drop/rise applied while the reduced setpoint is on. The panel rejects values below 2 °C; factory value 5 °C |
| Backup Source Start Dependency | 51 | 0–600 | Dependency between the target temperature and the time until the additional source starts (panel row 5, installation value 100) |
| Backup Source Start Delay | 52 | 1–120 min | Time until the additional source (heater, boiler) is started (panel page 2/2, first row, installation value 20 min) |

### Binary sensors

Enabled by default:

| Entity | Data key |
|---|---|
| Heating Circuit 2 Active | `Circuit2_Enabled` |

Every other binary sensor is disabled by default — enable individually via Settings → Entities:

| Entity | Data key |
|---|---|
| Circuit 2 Heating Curve | `Circuit2_HeatingCurve_State` |
| Shifting Priority | `Shifting_Priority` |
| DHW Backup Heater For Shifting Priority | `DHW_Backup_For_Shifting` |
| Reheating Function | `Reheating_Function` |
| Quiet Operation | `Quiet_Operation` |
| Electrical Utility Lock | `Electrical_Utility_Lock` |
| HBH Allowed During Electrical Utility Lock | `HBH_During_Lock` |
| P0 Allowed During Electrical Utility Lock | `P0_During_Lock` |
| Heating/Cooling ON/OFF Timer | `Heating_Cooling_Timer` |
| Room Temp Effect On Heating Curve | `Room_Temp_Effect_On_Curve` |
| Water Pump P1 | `WaterPump_P1` |
| Water Pump P2 | `WaterPump_P2` |

The integration also adds **Connection** (`ON` while the TCP socket to the W600 is live) and **Anti-Legionella Running** (`ON` when the programme is enabled and the pump is in DHW mode — the best available indicator of a running cycle).

### Sensors

Enabled by default:

| Entity | Data key | Unit |
|---|---|---|
| Outdoor Unit Outlet Temperature | `Tuo` | °C |
| Outdoor Unit Inlet Temperature | `Tui` | °C |
| Hot Water / DHW Temperature | `Tw` | °C |
| Heating Circuit Return Temperature | `Tc` | °C |
| Ambient Air Temperature | `Ta` | °C |
| Heating Water Setpoint | `Setpoint` | °C |
| Supply Voltage | `Voltage` | V |
| Compressor Current | `Current` | A |
| Compressor Frequency | `Frequency` | Hz |
| High-side Pressure | `Pd` | bar |
| Low-side Pressure | `Ps` | bar |
| Outdoor Unit Delta T | `DeltaT` | °C |
| Water Circuit Delta T | `DeltaT_water` | °C |
| Electrical Power | `Power` | W |
| Thermal Output Power | `Thermal_power` | W |
| COP Estimated | `COP_estimated` | None |
| AH Working Time | `Time_AH` | min |
| HBH Working Time | `Time_HBH` | min |
| HWTBH Working Time | `Time_HWTBH` | min |

Plus five sensors implemented as dedicated entities: **Working Mode** (Standby / Heating / DHW / …), **Mode Setting** (configured mode, cloud par4), **Water Pump** (text state), and two diagnostics: **Last Seen** and **Reconnect Count**.

Disabled by default (enable individually via Settings → Entities):

| Entity | Data key | Unit |
|---|---|---|
| Outdoor Unit Pipe Temperature | `Tup` | °C |
| EEV Temperature Sensor 1 | `Tv1` | °C |
| EEV Temperature Sensor 2 | `Tv2` | °C |
| Room Temperature | `Tr` | °C |
| Discharge Temperature Td | `Td` | °C |
| Suction Temperature Ts | `Ts` | °C |
| Liquid Line Temperature Tp | `Tp` | °C |
| Expansion Valve Opening | `EEV` | steps |
| Fan 1 Speed | `Fan1` | rpm |
| Fan 2 Speed | `Fan2` | rpm |
| Working Mode (raw) | `WorkingMode` | None |
| Water Pump (raw) | `WaterPump` | None |
| PWM | `PWM` | % |
| COP Carnot | `COP_carnot` | None |
| Vacation Mode DHW Temp Drop | `Vacation_DHW_Drop` | °C |
| Vacation Mode Heating Temp Drop | `Vacation_Heating_Drop` | °C |
| Circuit 2 Cooling Setpoint | `Circuit2_Cooling_Setpoint` | °C |
| Circuit 2 Curve Water 1 | `Circuit2_Curve_Water_1` | °C |
| Circuit 2 Curve Water 2 | `Circuit2_Curve_Water_2` | °C |
| Circuit 2 Curve Water 3 | `Circuit2_Curve_Water_3` | °C |
| Circuit 2 Curve Water 4 | `Circuit2_Curve_Water_4` | °C |
| Circuit 2 Curve Water 5 | `Circuit2_Curve_Water_5` | °C |
| Circuit 2 Heating Setpoint (no curve) | `Circuit2_Heating_Setpoint_NoCurve` | °C |
| Shifting Priority Starting Temp | `Shifting_Priority_Start_Temp` | °C |
| Sanitary Water Min Working Hours | `Sanitary_Min_Working_Hours` | h |
| Heating Max Working Hours | `Heating_Max_Working_Hours` | h |
| Allowable Temp Drift in Heating | `Allowable_Temp_Drift_Heating` | °C |
| Reheating Set Temp | `Reheating_Set_Temp` | °C |
| Reheating Restart DT | `Reheating_Restart_DT` | °C |
| Quiet Operation Allowable Temp Drift | `Quiet_Allowable_Drift` | °C |
| Cooling And Heating Switch (raw) | `Cooling_Heating_Switch` | None |
| Ambient Temp To Start Heating | `Ambient_Temp_Start_Heating` | °C |
| Ambient Temp To Start Cooling | `Ambient_Temp_Start_Cooling` | °C |
| Control Panel Backlight (raw) | `Panel_Backlight` | None |
| Circuit 2 Heating Curve Parallel Move | `Curve2_Parallel_Move` | °C |

> `COP Estimated` and `Thermal Output Power` are only computed while the pump is in **Heating** mode with the water pump running; in DHW mode they are `unknown` by design (the DHW tank and the floor-heating return are separate circuits, so a ΔT-based figure would be fiction).

## Backup heat sources (AH / HBH / HWTBH)

The pump knows up to three electric sources besides the compressor:

| Abbreviation | What it is |
|---|---|
| **AH** | Auxiliary heater built into the indoor unit (3 kW). Has no switch of its own in this menu |
| **HBH** | Backup heater in the heating buffer (space heating) |
| **HWTBH** | Backup heater in the DHW tank |

The panel menu *Dodatkowe źródła ciepła* maps to these entities:

| Panel row | Entity | Slot |
|---|---|---|
| 1 — additional source when heating (☐) | Backup Source For Heating | 47 |
| 2 — priority in the buffer when assisting heating | Backup Priority (Heating) | 48 |
| 3 — additional source when heating DHW (☐) | Backup Source For DHW | 49 |
| 4 — priority in the DHW tank when assisting DHW | Backup Priority (DHW) | 50 |
| 5 — dependency between target temperature and start time | Backup Source Start Dependency | 51 |
| page 2/2, row 1 — time until the additional source starts | Backup Source Start Delay | 52 |

**Priority** means the order of the stages: "Niższe dla grzałki wewnętrznej AH" (value 0) = the additional source has a *lower* priority than AH, so **AH goes first**; "Wyższe" (value 1) = the additional source goes first. Neither value turns a heater off. According to the user manual, when no HWTBH is installed (or it has a lower priority than AH) the pump starts AH first, then HWTBH.

Page 2/2 rows about blocking AH and the electrical-utility lock are on the installer level of the panel; they are **not** confirmed and have no writable entity (the read-only lock sensors above map to portal parameters only).

The working-time counters (`AH / HBH / HWTBH Working Time`, minutes) may reflect the controller's output signal rather than a measured power draw: on the reference installation the HWTBH counter grows on days when the pump's own consumption shows no extra kilowatts.

## Services

All services address every configured heat pump.

| Service | Parameters | Description |
|---------|-----------|-------------|
| `heiko_heatpump.set_dhw_setpoint` | `temperature` (40–60 °C) | Set DHW target temperature |
| `heiko_heatpump.set_heating_setpoint` | `temperature` (15–55 °C) | Set heating water target (only effective with the heating curve off) |
| `heiko_heatpump.set_mode` | `mode` (standby/heating/cooling/dhw/auto or 0–4) | Set working mode |
| `heiko_heatpump.set_power` | `power` (true/false) | Turn pump on or off |
| `heiko_heatpump.set_heating_curve` | `enabled` (true/false) | Enable/disable weather curve |
| `heiko_heatpump.set_hbh` | `enabled` (true/false) | Legacy: writes slot 50 (`true` = "lower than AH"). Prefer `set_backup_priority_dhw` |
| `heiko_heatpump.set_dhw_storage` | `enabled` (true/false) | Enable/disable DHW storage |
| `heiko_heatpump.set_vacation_mode` | `enabled` (true/false) | Enable/disable Vacation Mode |
| `heiko_heatpump.set_curve_parallel` | `shift` (−9…+9) | Parallel-shift the heating curve |
| `heiko_heatpump.set_heating_stops_delta` | `delta` (1–15 °C) | Set heating/cooling stop ΔT |
| `heiko_heatpump.set_heating_restarts_delta` | `delta` (1–15 °C) | Set heating/cooling restart ΔT |
| `heiko_heatpump.set_dhw_restart_delta` | `delta` (1–15 °C) | Set DHW restart ΔT |
| `heiko_heatpump.set_curve_ambient_temp` | `point` (1–5), `temperature` (−25…+20 °C) | Set one ambient breakpoint of the heating curve |
| `heiko_heatpump.set_curve_water_temp` | `point` (1–5), `temperature` (15–60 °C) | Set one water-temp breakpoint of the heating curve |
| `heiko_heatpump.set_anti_leg_program` | `enabled` (true/false) | Enable/disable the Anti-Legionella programme |
| `heiko_heatpump.set_anti_leg_setpoint` | `temperature` (40–70 °C) | Set legionella kill temperature |
| `heiko_heatpump.set_anti_leg_duration` | `minutes` (1–120) | Set how long to hold the setpoint |
| `heiko_heatpump.set_anti_leg_finish` | `minutes` (1–240) | Set cycle finish/timeout time |
| `heiko_heatpump.set_backup_heating` | `enabled` (true/false) | Additional heat source present when heating (slot 47) |
| `heiko_heatpump.set_backup_priority_heating` | `priority` (0 = lower than AH, 1 = higher) | Priority of the additional source when heating (slot 48) |
| `heiko_heatpump.set_backup_dhw` | `enabled` (true/false) | Additional heat source present for DHW (slot 49) |
| `heiko_heatpump.set_backup_priority_dhw` | `priority` (0 = lower than AH, 1 = higher) | Priority of the DHW additional source (slot 50) |
| `heiko_heatpump.set_backup_accum` | `value` (0–600) | Start dependency of the additional source (slot 51) |
| `heiko_heatpump.set_backup_start_delay` | `minutes` (1–120) | Time until the additional source starts (slot 52) |
| `heiko_heatpump.set_reduced_setpoint` | `enabled` (true/false) | Reduced setpoint on/off (slot 77) |
| `heiko_heatpump.set_reduced_drop` | `temperature` (2–10 °C) | Reduced-setpoint drop/rise (slot 78) |

The circulation pump P0 settings have no services — use the select/number entities.

## How the registers were mapped

Setdata slot numbers follow `idx = parN − 1` from the vendor portal's parameter list (`realtime: idx = parN + 1`), verified on 74 independent pairs with no mismatch. Newer parameters that the portal does not expose were named by **panel diffing**: change exactly one field on the physical controller, watch which single slot moves in the next setdata frame (`diagnostics` → `all_floats_setdata`, or the slot logging option), change it back. Circulation pump P0 was mapped this way on 2026-09-23; the reduced setpoint (slots 77/78) and the additional heat sources (slots 47–52) on 2026-09-26. Full session logs and the parameter map live in the [`homeassistant-config`](https://github.com/miczu71/homeassistant-config) repository (`docs/heiko_register_map.md`, `docs/heiko_controller_menu.md`).

Slots not (yet) confirmed and therefore read-only: quiet operation (79/80), electrical utility lock (82–84), and everything on the installer menu pages that could not be tested.

The weekly schedules of the controller (reduced setpoint, quiet operation, DHW storage, anti-legionella day/time) did not change any slot in the captured frames when edited on the panel (2026-09-26); they appear to be stored by the panel itself and are not available through this integration.

## Diagnostic tools (`tools/`)

Standalone scripts, not used by the integration. All require `--host YOUR_W600_IP`. Run from the repo root.

| Tool | Purpose |
|------|---------|
| `sniff_heatpump.py` | Passive frame sniffer on SocketA |
| `capture_writes.py` | Capture and decode CMD 0x05 write frames |
| `test_write_live.py` | Test a write command directly (bypasses HA) |
| `mitm_heatpump.py` | Transparent MITM proxy on SocketB (cloud link) |
| `diagnose_mode.py` | Identify WorkingMode payload index |

## Running tests

```bash
python tests/test_protocol.py
```

No HA installation required — the tests load only `protocol.py`.
