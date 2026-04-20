# apply-discoveries — Turn capture session output into integration code

## Context — what this integration is

Custom Home Assistant integration for a **Heiko / Neoheat Eko II 6kW heat pump**
connected via a USR-W600 WiFi-to-RS-485 bridge (192.168.1.100:8899).

The integration lives in `custom_components/heiko_heatpump/` and consists of:

```
__init__.py      — setup/teardown, loads platforms
protocol.py      — frame parser, float extraction, write frame builders
coordinator.py   — DataUpdateCoordinator, TCP client owner, write methods
sensor.py        — read-only sensor entities
number.py        — writable numeric entities (setpoints)
select.py        — writable enum entities (modes)
switch.py        — power on/off switch
climate.py       — thermostat card (mode + heating setpoint)
tcp_client.py    — async TCP client with reconnect
const.py         — constants
```

## Confirmed write indices (already implemented)

```
Write index 0  → Power            (1=on, 0=off)
Write index 3  → WorkingMode      (1=Heating, 2=Cooling, 3=DHW, 4=Auto, 0=Standby)
Write index 37 → Heating setpoint (°C)
Write index 54 → DHW setpoint     (°C)
```

## Protocol constants you must follow

```python
# Payload offset formula (confirmed empirically):
payload_offset = 2 + index * 4

# Frame builder pattern (see protocol.py build_write_param):
payload = struct.pack('<H', write_index) + struct.pack('<f', value)
# Full frame: AA 55 01 <MN:6> 01 <len:2 LE> 05 <payload> <CRC:2 LE> 3A
# MN = a1b2c3d4e5f6, Target = 0x01, DevID = 0x01

# Write index formula (verified):
write_index = cloud_setdata_parN - 1
```

## What to paste

Paste the discovery summary from a `/capture` session. It looks like:

```
═══ SESSION DISCOVERY SUMMARY ═══
[parameter table]
[new discoveries table]
[setdata unknowns]
[next steps]
═══════════════════════════════
```

## What this command does

For each new write index discovered:

1. Add to `protocol.py`:
   ```python
   WRITE_IDX_NEWPARAM = N
   
   def build_set_newparam(mn: bytes, value: float, **kwargs) -> bytes:
       """Set [param name]. Write index N. Confirmed by traffic capture [date]."""
       return build_write_param(mn, WRITE_IDX_NEWPARAM, value, **kwargs)
   ```

2. Add to `coordinator.py`:
   ```python
   async def async_set_newparam(self, value: float) -> None:
       """[description]. Write index N."""
       await self._send_write(build_set_newparam(self._mn, value), f"NewParam → {value}")
   ```

3. Add the appropriate HA platform entity:
   - Temperature setpoint (°C, writable) → `number.py` slider
   - Mode / enum (writable, known values) → `select.py` dropdown  
   - Boolean (on/off, writable) → `switch.py`
   - Read-only from setdata → `sensor.py` SENSOR_DESCRIPTIONS entry

4. For new **read-only** setdata slots (seen in CMD 0x02 but no CMD 0x05 confirmed):
   - Add to `sensor.py` only, with a note "read from setdata CMD 0x02, write unconfirmed"

## Decision guide

| Observed value pattern | Likely type | Platform |
|------------------------|-------------|----------|
| 0.0 or 1.0 only | Boolean / on-off | switch |
| Integer 0–5 | Enum / mode | select |
| Float 20–65 | Temperature setpoint | number |
| Float varies, not settable | Read-only sensor | sensor |

## Safety rules

- **Never remove** existing `WRITE_IDX_*` constants or `build_set_*` functions
- **Never change** an existing confirmed write index
- If a discovered index contradicts an existing one — **stop and ask**
- If the write index formula (`cloud_parN - 1`) doesn't fit a discovery — flag it
- Mark all new additions with `# Confirmed by traffic capture` comment

## After making changes

Run the integration tests if available:
```bash
python3 tests/test_protocol.py
```

Then print:
```
Changes made:
  protocol.py   — added WRITE_IDX_X = N, build_set_X()
  coordinator   — added async_set_X()
  number.py     — added slider for X (range A–B °C)
  [etc]

Tests: N passed, 0 failed

Commit message suggestion:
  "Add [parameter] write support (write index N, confirmed by capture)"
```
