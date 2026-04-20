# Heiko Heat Pump — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/v/release/miczu71/heiko-heatpump-ha)](https://github.com/miczu71/heiko-heatpump-ha/releases)

Local-only (no cloud) Home Assistant custom integration for **Heiko / Neoheat / ECOtouch** heat pumps connected via a **USR-W600 WiFi-to-RS-485 bridge**.

## How it works

The USR-W600 acts as a transparent TCP server on port 8899. The heat pump pushes binary frames every ~10 s (CMD 0x01 realtime + CMD 0x02 setdata). This integration connects as a TCP client, parses those frames, and exposes all parameters as HA entities. It also polls every 60 s as a fallback and writes settings back via CMD 0x05.

Frame format and all write indices were confirmed by MITM-capturing live cloud→pump traffic — no guessing.

## Features

- **Water heater entity** — DHW setpoint control (40–60 °C, step 1 °C), current water temperature, operation mode
- **4 switch entities** — Heat Pump Power, Heating Curve, Backup Heater (HBH), DHW Storage
- **Working Mode select** — direct mode control (Standby / Heating / Cooling / DHW / Auto)
- **30+ sensor entities** — temperatures, pressures, compressor frequency, electrical, COP estimates, working-time counters
- **Connection binary sensor** — shows whether the TCP link to the W600 is live
- **6 HA services** — control the pump from automations (`set_dhw_setpoint`, `set_mode`, `set_power`, `set_heating_curve`, `set_hbh`, `set_dhw_storage`)
- **Repairs alert** — raises an issue in Settings → Repairs if the pump stops sending data for 5+ minutes, with troubleshooting steps; clears automatically on recovery
- **Diagnostics** — download all sensor values as JSON from the device page (host/MN redacted)
- **Options flow** — edit host, port, MN, and flow rate after setup via Settings → Devices & Services → Configure
- **Local push** — entities update within seconds of each pump frame
- **TCP reconnect** — exponential backoff on connection loss
- **No cloud required** — all communication is direct TCP to the W600 bridge

## Tested hardware

- Heiko Eko II heat pumps
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

Settings can be changed after setup via **Settings → Devices & Services → Heiko Heat Pump → Configure**.

The MN is used to address CMD 0x05 write frames. The integration also learns the pump's own MN from its first CMD 0x01 frame and uses that for subsequent writes.

## W600 setup

The W600 must be in **SocketA TCP Server** mode:
- Protocol: TCP
- Local port: 8899
- Transfer mode: Transparent

No changes to SocketB are needed for local-only use.

## Entities

### Water Heater
| Entity | Description |
|--------|-------------|
| DHW | Target = DHW setpoint (40–60 °C), current = water outlet temp (Tw), operation mode |

### Binary Sensors
| Entity | Description |
|--------|-------------|
| Connection | `ON` when the TCP socket to the W600 is live |

### Switches
| Entity | Description |
|--------|-------------|
| Heat Pump Power | Power on/off |
| Heating Curve | Weather-compensated heating curve on/off |
| Backup Heater (HBH) | Auxiliary electric heater on/off |
| DHW Storage | DHW storage mode on/off |

### Sensors (selection)
| Key | Description |
|-----|-------------|
| Hot Water / DHW Temperature (Tw) | Current DHW / water outlet temperature |
| Ambient Air Temperature (Ta) | Outdoor ambient temperature |
| Compressor Frequency | Compressor speed in Hz |
| Electrical Power | Calculated V × I in watts |
| COP Estimated | Thermal output / electrical input (when compressor running) |
| High/Low-side Pressure (Pd/Ps) | Refrigerant circuit pressures |
| Working Mode | Instantaneous operating state (Standby / Heating / DHW / …) |
| Mode Setting | Configured working mode (equivalent to cloud par4) |
| AH / HBH / HWTBH Working Time | Accumulated run-time counters |
| Last Seen | Timestamp of last received frame (diagnostic) |
| Reconnect Count | TCP reconnection counter since HA start (diagnostic) |

> Several technical sensors (EEV, PWM, fan speeds, refrigerant temps) are created but **disabled by default**. Enable them individually via Settings → Entities if needed.

### Services

| Service | Parameters | Description |
|---------|-----------|-------------|
| `heiko_heatpump.set_dhw_setpoint` | `temperature` (40–60) | Set DHW target temperature |
| `heiko_heatpump.set_mode` | `mode` (standby/heating/cooling/dhw/auto) | Set working mode |
| `heiko_heatpump.set_power` | `power` (true/false) | Turn pump on or off |
| `heiko_heatpump.set_heating_curve` | `enabled` (true/false) | Enable/disable weather curve |
| `heiko_heatpump.set_hbh` | `enabled` (true/false) | Enable/disable backup heater |
| `heiko_heatpump.set_dhw_storage` | `enabled` (true/false) | Enable/disable DHW storage |

## Diagnostic tools (`tools/`)

All tools require `--host YOUR_W600_IP`. Run from the repo root.

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

No HA installation required — imports only `protocol.py`.
