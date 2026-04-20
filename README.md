# Heiko Heat Pump — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Local-only (no cloud) Home Assistant custom integration for **Heiko / Neoheat / ECOtouch** heat pumps connected via a **USR-W600 WiFi-to-RS-485 bridge**.

## How it works

The USR-W600 acts as a transparent TCP server on port 8899. The heat pump pushes binary frames every ~10 s (CMD 0x01 realtime + CMD 0x02 setdata). This integration connects as a TCP client, parses those frames, and exposes all parameters as HA entities. It also polls every 60 s as a fallback and writes settings back via CMD 0x05.

Frame format and all write indices were confirmed by MITM-capturing live cloud→pump traffic — no guessing.

## Features

- **Climate entity** — thermostat card with DHW setpoint control (40–60 °C, step 1 °C), working-mode preset (Heating / DHW / Auto / Cooling), current water temperature
- **4 switch entities** — Heat Pump Power, Heating Curve, Backup Heater (HBH), DHW Storage
- **2 number entities** — DHW Setpoint input
- **Working Mode select** — direct mode control (Standby / Heating / Cooling / DHW / Auto)
- **30+ sensor entities** — temperatures, pressures, compressor frequency, fans, current, voltage, EEV, working-time counters, COP estimates
- **Mode Setting sensor** — configured mode (replaces cloud par4 sensor)
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
| MN | `F4700C77F01A` | Unit identifier — the W600's WiFi MAC address (no colons), found on the W600 label or in its web UI under **Device Info → MAC** |

The MN is used to address CMD 0x05 write frames. The integration also learns the pump's own MN from its first CMD 0x01 frame and uses that for subsequent writes.

## W600 setup

The W600 must be in **SocketA TCP Server** mode:
- Protocol: TCP
- Local port: 8899
- Transfer mode: Transparent

No changes to SocketB are needed for local-only use.

## Entities

### Climate
| Entity | Description |
|--------|-------------|
| Heat Pump | Thermostat — target = DHW setpoint, current = water outlet temp, preset = working mode |

### Switches
| Entity | Description |
|--------|-------------|
| Heat Pump Power | Power on/off |
| Heating Curve | Weather-compensated curve on/off |
| Backup Heater (HBH) | Auxiliary heater on/off |
| DHW Storage | DHW storage mode on/off |

### Sensors (selection)
| Key | Index | Description |
|-----|-------|-------------|
| Tw | 8 | Water / DHW outlet temperature |
| Ta | 25 | Ambient air temperature |
| Frequency | 21 | Compressor frequency (Hz) |
| Current / Voltage | 31 / 32 | Electrical input |
| Pd / Ps | 23 / 24 | High/low-side refrigerant pressure |
| WorkingMode | 2 | Instantaneous operating state (CMD 0x01) |
| Mode Setting | — | Configured working mode (CMD 0x02, par4 equivalent) |

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
