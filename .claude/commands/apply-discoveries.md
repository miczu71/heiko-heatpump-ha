# apply-discoveries — Turn capture session output into integration code

After running `/capture`, paste the session discovery summary here and this command will update the integration files.

## What to paste

Paste either:
- The full terminal output from the capture session, OR
- Just the discovery summary table at the end

## What this command does

1. **Reads** the current `custom_components/heiko_heatpump/protocol.py` and `coordinator.py`
2. **Parses** new write indices from the pasted session output
3. **Updates** protocol.py:
   - Adds new `WRITE_IDX_*` constants
   - Adds new `build_set_*()` functions
4. **Updates** coordinator.py:
   - Adds new `async_set_*()` methods
5. **Creates or updates** the appropriate HA platform file:
   - New writable parameter → `number.py` (if numeric °C or %) or `select.py` (if enum)
   - New readable parameter → entry in `sensor.py` SENSOR_DESCRIPTIONS
6. **Runs the test suite** to verify nothing is broken
7. **Prints a diff summary** of every change made

## Decision rules

| Discovered parameter type | Platform to add |
|--------------------------|-----------------|
| Temperature setpoint (°C, writable) | `number.py` — slider |
| Mode / enum (writable) | `select.py` — dropdown |
| On/Off (writable) | `switch.py` — toggle |
| Read-only temperature | `sensor.py` — temperature sensor |
| Read-only numeric | `sensor.py` — measurement sensor |
| Unknown type | Ask the user before adding |

## Output

After making changes, print:

```
Changes made:
  protocol.py  — added WRITE_IDX_X = N, build_set_X()
  coordinator  — added async_set_X()
  number.py    — added HeikoNumberEntity for X
  sensor.py    — added sensor description for Y

Tests: N passed, 0 failed

Ready to package. Run: git add -A && git commit -m "..."
```

## Safety rules

- Never remove existing constants or functions — only add
- Never change existing write indices that are already confirmed
- If the pasted data contradicts an existing confirmed index, flag it and ask before changing
- If a new setdata slot index appears in CMD 0x02 but no corresponding CMD 0x05 was observed, add it as read-only sensor only (not writable) until confirmed
