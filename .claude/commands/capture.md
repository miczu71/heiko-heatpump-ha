# capture — Heat pump protocol capture & decode

Connect to the Heiko heat pump RS-485 bridge at **192.168.0.82:8899** and capture all frames in real time.

## Your job

1. Open a persistent TCP connection to `192.168.0.82:8899`
2. Continuously read and decode every frame
3. Print a clean, structured decode for every frame received
4. When the user says **"done"** or **"stop"**, print a full summary of everything captured

## Frame format

```
AA 55  <target:1>  <MN:6>  <devid:1>  <content_len:2 LE>  <cmd:1>  <payload:n>  <CRC:2 LE>  3A
```

Header = 13 bytes before payload. Content_len = payload_len + 1. End byte = 0x3A.

## Commands

| CMD  | Direction     | Meaning              | Frequency        |
|------|---------------|----------------------|------------------|
| 0x01 | pump → us     | Realtime sensor data | every ~30s       |
| 0x02 | pump → us     | Setdata snapshot     | every ~3min      |
| 0x03 | us → pump     | ACK realtime         | after each 0x01  |
| 0x04 | us → pump     | ACK setdata          | after each 0x02  |
| 0x05 | cloud → pump  | **Write command**    | on user action   |
| 0x06 | us → pump     | Poll request         | on demand        |

## Payload decoding

**CMD 0x01 and 0x02** — float array:
- 2-byte prefix (skip)
- Then IEEE 754 LE floats at `offset = 2 + index * 4`
- Print ALL non-zero slots with their index

**CMD 0x05** — write command:
```
payload[0:2] = uint16 LE  → parameter index
payload[2:6] = float32 LE → value
```

## Known register map (for annotation)

### Realdata (CMD 0x01) — read indices
| Index | Name         | Unit  | Notes                        |
|-------|--------------|-------|------------------------------|
| 2     | WorkingMode  |       | 0=Standby 1=Heating 3=DHW 4=Auto |
| 5     | Tuo          | °C    | Outdoor unit outlet          |
| 6     | Tui          | °C    | Outdoor unit inlet           |
| 7     | Tup          | °C    | Outdoor unit pipe            |
| 8     | Tw           | °C    | Hot water / DHW              |
| 9     | Tc           | °C    | Heating circuit return       |
| 12    | Tr           | °C    | Room temperature             |
| 13    | PWM          | %     |                              |
| 21    | Frequency    | Hz    | Compressor                   |
| 22    | EEV          | steps | Expansion valve              |
| 23    | Pd           | bar   | High-side pressure           |
| 24    | Ps           | bar   | Low-side pressure            |
| 25    | Ta           | °C    | Ambient air                  |
| 26    | Td           | °C    | Discharge temperature        |
| 27    | Ts           | °C    | Suction temperature          |
| 28    | Tp           | °C    | Liquid line temperature      |
| 29    | Fan1         | rpm   |                              |
| 30    | Fan2         | rpm   |                              |
| 31    | Current      | A     | Compressor                   |
| 32    | Voltage      | V     |                              |
| 34    | WaterPump    |       | 1=on 0=off                   |
| 37    | Setpoint     | °C    | Heating circuit target       |

### Setdata (CMD 0x05 write indices) — confirmed
| Write Index | Parameter        | Notes                             |
|-------------|------------------|-----------------------------------|
| 0           | Power            | 1=on 0=off                        |
| 3           | WorkingMode      | 1=Heating 3=DHW 4=Auto            |
| 37          | Heating setpoint | °C                                |
| 54          | DHW setpoint     | °C                                |

**Unknown write indices** — to be discovered during this session.

## Output format

### For CMD 0x05 (write) — most important:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⬆  CMD 0x05  WRITE  [HH:MM:SS]
   Index : 3      ← known: WorkingMode
   Value : 1.0    ← Heating
   Raw   : 03 00 00 00 80 3f
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### For CMD 0x02 (setdata snapshot) — decode all non-zero slots:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⬇  CMD 0x02  SETDATA SNAPSHOT  [HH:MM:SS]
   [  0]  1.0    Power (on)
   [  3]  1.0    WorkingMode (Heating)
   [ 37]  28.0   Heating setpoint
   [ 54]  48.0   DHW setpoint
   [ xx]  yy.y   ← UNKNOWN — note for mapping
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### For CMD 0x01 (realtime) — compact:
```
⬇  CMD 0x01  [HH:MM:SS]  Mode=Heating  Freq=90Hz  Tw=48.7°C  Tc=24.1°C  Ta=10.5°C  I=6.8A
```

## Session workflow

1. Start capture, print "Listening on 192.168.0.82:8899 — make changes on the pump panel now"
2. User announces what they're about to change (e.g. "changing DHW setpoint to 52°C")
3. Capture the resulting CMD 0x05 frame(s), decode and annotate
4. Cross-check: does the CMD 0x02 setdata snapshot (next ~3min) confirm the change?
5. On "done" — print the **discovery summary table**:

```
┌─────────────────────────────────────────────────────────────────────┐
│                     SESSION DISCOVERY SUMMARY                        │
├──────────────────┬──────────────┬────────────────────────────────── │
│ Parameter        │ Write index  │ Values observed                    │
├──────────────────┼──────────────┼────────────────────────────────── │
│ Power            │ 0            │ 1=on, 0=off  ← confirmed           │
│ Working mode     │ 3            │ 1=Heating, 3=DHW, 4=Auto           │
│ Heating setpoint │ 37           │ numeric °C                         │
│ DHW setpoint     │ 54           │ numeric °C                         │
│ [new discovery]  │ ??           │ ??                                 │
└──────────────────┴──────────────┴────────────────────────────────── │

SETDATA frame unknown slots (from CMD 0x02):
  Index XX → value YY  [seen N times, always same = likely config]
  Index XX → value YY  [varies = dynamic parameter]

RECOMMENDED NEXT STEPS for integration:
  - Add write support for: [list new indices]
  - Add read sensors for: [list new setdata slots]
  - Verify: [list anything ambiguous]
```

## Important notes

- Reconnect automatically if the connection drops (exponential backoff 1s→30s)
- The pump sends CMD 0x01 every ~30s even with no action — use these as a baseline
- CMD 0x05 frames arrive on our socket because the USR-W600 bridges ALL RS-485 traffic, including what the cloud server sends
- If no CMD 0x05 appears within 60s of an announced change, say so — the change may have gone via a different path
- Flag any index not in the known map above as **NEW DISCOVERY** with a highlight
