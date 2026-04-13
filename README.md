# Heiko Heat Pump — Home Assistant Integration

Local-only (no cloud) Home Assistant custom integration for **Heiko / Neoheat / ECOtouch** heat pumps connected via a **USR-W600 WiFi-to-RS-485 bridge**.

## How it works

The USR-W600 acts as a transparent TCP server on port 8899. The heat pump pushes binary frames every ~30 s (CMD 0x01). This integration connects as a TCP client, parses those frames, and exposes all parameters as HA entities. It also polls every 60 s as a fallback and can write setpoint / power state back via CMD 0x05.

## Features

- **24 sensor entities** — temperatures, pressures, compressor frequency, fans, current, voltage, EEV opening, working time counters
- **Climate entity** — thermostat card with setpoint control and working-mode readback (Standby / DHW / Heating / Cooling)
- **Switch entity** — power on/off
- **Local push** — entities update within seconds of each 30 s pump frame, no polling delay
- **TCP reconnect** — exponential backoff (1 s → 60 s) on connection loss
- **No cloud** — all traffic stays on 192.168.0.82:8899

## Installation

1. Copy `custom_components/heiko_heatpump/` into your HA `config/custom_components/` folder.
2. Restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → Heiko Heat Pump**
4. Fill in:
   - Bridge IP: `192.168.0.82`
   - Port: `8899`
   - MN (unit MAC): `F4700C77F01A`

## Parameter index reference

All parameters are IEEE 754 little-endian floats. Payload offset = `2 + index × 4`.

| Entity | Protocol index | Cloud parN | Notes |
|---|---|---|---|
| Tuo | 5 | par4 | Outdoor unit outlet temp |
| Tui | 6 | par5 | Outdoor unit inlet temp |
| Tup | 7 | par6 | Outdoor unit pipe temp |
| Tw (Water/DHW) | 8 | par7 | DHW in standby, heating water in heat mode |
| Tc | 9 | par8 | Condenser temp |
| Tr | 12 | par11 | Refrigerant temp |
| WorkingMode | 19 | par18 | 0=Standby 1=DHW 2=Heat 3=Cool 4=DHW+Heat 5=DHW+Cool |
| Frequency | 21 | par20 | Compressor Hz |
| EEV | 22 | par21 | Expansion valve steps |
| Pd | 23 | par22 | High-side pressure (bar) |
| Ps | 24 | par23 | Low-side pressure (bar) |
| Ta | 25 | par24 | Ambient air temp |
| Fan1 / Fan2 | 29 / 30 | par28/29 | Fan speeds |
| Current | 31 | par30 | Compressor current (A) |
| Voltage | 32 | par31 | Supply voltage (V) |
| WaterPump | 34 | par33 | 1.0 = running |
| Setpoint | 37 | par36 | Heating water setpoint (°C) |

## CRC

CRC-16/Modbus (poly 0x8005, init 0xFFFF). Cannot be verified from the truncated example frame in community docs. If you see consistent CRC mismatch warnings, change `_compute_crc = crc16_ccitt` in `protocol.py`.

## Running tests

```bash
python tests/test_protocol.py
```

No HA installation required — the test file imports only `protocol.py`.
