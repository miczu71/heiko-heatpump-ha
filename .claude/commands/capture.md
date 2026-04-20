# capture — Heiko heat pump protocol capture & decode

You are a protocol reverse-engineering assistant for a Heiko / Neoheat heat pump.

## Connection

Connect via TCP to **192.168.1.100:8899** (USR-W600 WiFi-to-RS-485 bridge).
This is a transparent byte pipe to the pump's RS-485 bus — all traffic is visible here,
including frames sent by the cloud server.

Reconnect automatically on disconnect with exponential backoff (1 s → 2 s → 4 s → 30 s max).

## Frame structure

```
[0-1]  AA 55               Header
[2]    01                  Target
[3-8]  f4 70 0c 77 f0 1a   MN (unit MAC address)
[9]    01                  Device ID
[10-11] LL LL              Content length, little-endian uint16 = payload_len + 1
[12]   CC                  Command byte
[13..] PP PP ...           Payload (content_len - 1 bytes)
[n-2]  CR CR               CRC-16 Modbus, little-endian
[n-1]  3A                  End byte
```

Parse frames by: find AA 55, read content_len at offset 10, compute total size = 13 + (content_len-1) + 3, validate end byte = 0x3A.

## Command bytes

| CMD  | Direction    | Name            | Cadence         |
|------|--------------|-----------------|-----------------|
| 0x01 | pump → us    | Realtime data   | every ~30 s     |
| 0x02 | pump → us    | Setdata snapshot| every ~3 min    |
| 0x03 | us → pump    | ACK realtime    | —               |
| 0x04 | us → pump    | ACK setdata     | —               |
| **0x05** | **cloud → pump** | **Write command** | **on user action** |
| 0x06 | us → pump    | Poll request    | —               |

## Payload decoding

### CMD 0x01 and CMD 0x02 — float array
- Skip first 2 bytes (sub-header)
- Float at index N: `struct.unpack_from('<f', payload, 2 + N*4)`
- Print ALL slots where `abs(value) > 0.001`

### CMD 0x05 — write command
```python
index = struct.unpack_from('<H', payload, 0)[0]   # uint16 LE
value = struct.unpack_from('<f', payload, 2)[0]   # float32 LE
```

## Known register map

### Realdata read indices (CMD 0x01)
```
Idx  Name          Unit   Notes
  2  WorkingMode          0=Standby 1=Heating 2=Cooling 3=DHW 4=Auto
  5  Tuo           °C     Outdoor unit outlet
  6  Tui           °C     Outdoor unit inlet
  7  Tup           °C     Outdoor unit pipe
  8  Tw            °C     Hot water / DHW outlet
  9  Tc            °C     Heating circuit return
 12  Tr            °C     Room temperature
 13  PWM           %
 21  Frequency     Hz     Compressor
 22  EEV           steps  Expansion valve opening
 23  Pd            bar    High-side pressure
 24  Ps            bar    Low-side pressure
 25  Ta            °C     Ambient air
 26  Td            °C     Discharge temperature
 27  Ts            °C     Suction temperature
 28  Tp            °C     Liquid line temperature
 29  Fan1          rpm
 30  Fan2          rpm
 31  Current       A      Compressor
 32  Voltage       V
 34  WaterPump            1=on 0=off
 37  Setpoint      °C     Heating circuit target
```

### Confirmed write indices (CMD 0x05)
```
WIdx  Parameter         Values confirmed
   0  Power             1.0=on  0.0=off
   3  WorkingMode       1=Heating  3=DHW  4=Auto
  37  Heating setpoint  numeric °C
  54  DHW setpoint      numeric °C
```

Any write index NOT in the list above is a **NEW DISCOVERY** — flag it clearly.

## Output format

### CMD 0x05 — write (most important, flag prominently)
```
╔══════════════════════════════════════════════════════════╗
║  ⬆ WRITE  CMD 0x05  [15:34:36]                          ║
║  Index : 54          ← DHW setpoint                     ║
║  Value : 49.0 °C                                        ║
║  Raw   : 36 00 00 00 44 42                              ║
╚══════════════════════════════════════════════════════════╝
```

If the index is NOT in the known map:
```
╔══════════════════════════════════════════════════════════╗
║  ⬆ WRITE  CMD 0x05  [15:34:36]  *** NEW DISCOVERY ***  ║
║  Index : 12          ← UNKNOWN                          ║
║  Value : 2.0                                            ║
║  Raw   : 0c 00 00 00 00 40                              ║
╚══════════════════════════════════════════════════════════╝
```

### CMD 0x02 — setdata snapshot (decode all non-zero slots)
```
┌─ SETDATA SNAPSHOT  CMD 0x02  [15:33:00] ──────────────────
│  [  0]   1.0   Power (on)
│  [  3]   1.0   WorkingMode (Heating)
│  [ 37]  28.0   Heating setpoint
│  [ 54]  49.0   DHW setpoint
│  [ XX]  YY.Y   *** UNKNOWN SLOT — note for mapping ***
└───────────────────────────────────────────────────────────
```

### CMD 0x01 — realtime (compact, one line)
```
⬇ RT [15:34:00] Mode=1(Heating) Freq=90Hz Tw=48.7 Tc=24.1 Ta=10.5 I=6.8A V=240V EEV=233
```

## Session workflow

1. Connect and print: `Listening on 192.168.1.100:8899 — ready. Tell me what you're about to change.`
2. User announces a change (e.g. *"changing cooling setpoint to 18°C"*)
3. User makes the change on the pump panel or remote
4. You capture and decode the resulting CMD 0x05 frame(s)
5. You confirm: *"Captured. Write index 7, value 18.0. This is a NEW DISCOVERY — cooling setpoint."*
6. Repeat for each parameter
7. When user says **"done"** — print the full summary:

## End-of-session summary (print on "done")

```
═══════════════════════════════════════════════════════════════
  SESSION DISCOVERY SUMMARY
═══════════════════════════════════════════════════════════════

CONFIRMED WRITE COMMANDS OBSERVED THIS SESSION:
┌──────────────────────┬─────────────┬──────────────────────┐
│ Parameter            │ Write index │ Values observed      │
├──────────────────────┼─────────────┼──────────────────────┤
│ [each CMD 0x05 seen] │ N           │ value1, value2...    │
└──────────────────────┴─────────────┴──────────────────────┘

NEW DISCOVERIES (not in known map):
┌──────────────────────┬─────────────┬──────────────────────┐
│ Guessed parameter    │ Write index │ Values / notes       │
├──────────────────────┼─────────────┼──────────────────────┤
│ ???                  │ N           │ observed: X.X        │
└──────────────────────┴─────────────┴──────────────────────┘

SETDATA FRAME UNKNOWNS (from CMD 0x02, read-only until write confirmed):
  Index XX: value YY.Y — seen N times — [constant / varies]

REALTIME ANOMALIES (values that changed after a write):
  Index XX changed from A → B after writing [parameter]

═══════════════════════════════════════════════════════════════
  NEXT STEPS FOR INTEGRATION
═══════════════════════════════════════════════════════════════
  Add write support : [list new write indices with guessed names]
  Add read sensors  : [list new setdata slots with guessed names]
  Verify            : [list anything ambiguous]

  Share this summary in the main Claude chat to update the integration.
═══════════════════════════════════════════════════════════════
```

## Implementation

Write the capture logic in Python directly in the terminal (no files needed).
Use a single script that loops forever until the user types "done".
Handle partial frames by buffering.
Print output immediately as frames arrive — do not batch.
