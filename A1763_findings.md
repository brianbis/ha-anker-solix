# A1763 (SOLIX C1000 Gen 2) — TOU Control: Findings & Integration

Captured 2026-08-29/30 from 5 live A1763 units (SNs `AXDDJWU0F38500{392,715,093,371,609}`),
US region (`aiot-mqtt-us.anker.com:8883`), firmware v1.1.4.1 (4 units) / v1.1.2.6 (living room).

Method: passive capture of BOTH `dt/` (telemetry) and `cmd/` (app commands) topics while the
user made controlled changes in the Anker app (TOU schedule edits incl. a 6-slot schedule,
TOU-power SOC, storm guard, fast-charge plan, usage-mode toggles, currency change). Every
mapping below was verified by decoding real captured bytes AND re-encoding to the exact
captured hex. Correlations (command→ACK, command→status) were verified across the whole
capture, not spot-checked. The cloud REST side was confirmed with live read/write probes and
static analysis of the official Anker app binary.

---

## 1. Headline findings (most important first)

### 1.1 The app's TOU schedule is stored in the cloud, not the device

The Anker app reads the PPS TOU schedule from a **cloud-side store**, not the device. The
save flow is:

```
app  →  REST  →  cloud (authoritative TOU store)  →  MQTT 0090 (client_id:"cloud")  →  device
device →  MQTT 0421  →  cloud (telemetry)
```

Evidence:
- The `0090` the cloud publishes after an app save has `head.client_id == "cloud"` — the
  *cloud* pushes it to the device; the app never sends `0090` directly.
- A direct MQTT `0090` from an external client is **executed by the device** (device screen +
  `0421` telemetry update) but is **NOT recorded in the cloud store**, so the app keeps
  showing the old schedule.
- Confirmed over 24h: the cloud pushed the app's schedule down to the device overnight —
  the cloud store is authoritative, the device is a follower.

**Consequence:** controlling the TOU schedule end-to-end (device + app) requires writing the
cloud store via REST, not just sending MQTT.

### 1.2 The cloud TOU store: `pps_use_time` device attribute (FOUND)

The PPS TOU schedule is stored in the **`pps_use_time`** device attribute, read/written via the
generic `get_device_attrs` / `set_device_attrs` REST endpoints:

- **GET** `power_service/v1/app/device/get_device_attrs`
  `{"device_sn": SN, "attributes": ["pps_use_time"]}`
- **SET** `power_service/v1/app/device/set_device_attrs`
  `{"device_sn": SN, "attributes": {"pps_use_time": "<JSON string>"}}`

`pps_use_time` is a **JSON string** (not a nested object):

```json
{
  "ranges": [
    {"start_time": "00:00", "end_time": "09:00", "type": 1},
    {"start_time": "09:00", "end_time": "19:00", "type": 3},
    {"start_time": "19:00", "end_time": "24:00", "type": 1}
  ],
  "prices": [{"price": "0.2", "type": 1}, {"price": "0.05", "type": 2}, {"price": "0.001", "type": 3}],
  "unit": "$",
  "reserve_power": 6
}
```

- `type` maps 1:1 to the MQTT `0090` tariff values (1=Peak, 2=Mid, 3=Off) — the cloud calls it
  `type`, the schedule dict calls it `tariff`.
- `reserve_power` is the backup-SOC reserve (the cloud's authoritative value; the device's
  `backup_soc` drifts from it when set via raw MQTT).
- `prices`/`unit` are the per-tariff prices and currency (server-side).

**How it was found:** the consumer app is a Flutter app (`com.anker.charging`, official APK
served from Anker's S3). Static string analysis of `libapp.so` surfaced `pps_use_time`,
`peak_valley_*` beans, and `setTouElectricAttrs` → `attributes{pps_use_time}`. Cross-checked
against the community reverse-engineering notes (moag1000/anker-solix-api-exploration), which
confirmed `setTouElectricAttrs` uses `attributes{pps_use_time}`.

### 1.3 The MQTT `0090` must be full-state with an `fe` timestamp

Two fixes were required for the MQTT `0090` to be recorded by the cloud (not just applied to
the device):

1. **Timestamp field is `fe` (4-byte unix-seconds LE), NOT `fd` (14-byte ASCII ms).** Every
   A1763 command the app sends uses `fe` (`0040`, `0057`, `0100`, `0090` all confirmed). The
   integration's default `CMD_COMMON_V2` uses `fd` (ms string) — that mismatch is why an
   `fd`-timestamped `0090` updates the device locally but is not recorded by the cloud.
2. **The app sends the FULL state in one `0090`**: `a1, a2, a3, a4, a5, a6, a7, fe` (in that
   order). A partial `0090` (only `a6`+`a7`) is merged by the device but the cloud only
   records the schedule when the command carries the full state with an `fe` timestamp.

**Verified byte-for-byte:** the `pps_tou_schedule` encoder (full state + `fe` timestamp, app
field order — the `CMD_TOU_PLAN_FULL_V2` map) reproduces the app's captured `0090` exactly:
```
app : ff093a0003000f0090a10122a2020101a3020100a4020100a5020133a6020105a7100401000a030a0c020c0d030d13011318fe0503f83b936a2b
mine: ff093a0003000f0090a10122a2020101a3020100a4020100a5020133a6020105a7100401000a030a0c020c0d030d13011318fe0503f83b936a2b
MATCH: True
```

---

## 2. The TOU feature, end-to-end (what the integration delivers)

The `modify_solix_use_time` service now controls the PPS TOU schedule **end-to-end** — both the
device and the Anker app reflect the change. The author's existing service (previously
SB2-seasonal-only, backed by `set_sb2_use_time` marked "NOT IMPLEMENTED YET") is **extended**
rather than a parallel service being added: it branches on the entity feature. One call applies
two paths:

1. **MQTT `0090` (device, immediate):** a full-state command (usage mode + backup SOC +
   schedule) sent exactly as the app sends it. Updates the device directly.
2. **Cloud store (app-visible, authoritative):** a commit to the `pps_use_time` attribute via
   `set_device_attrs`. The cloud then pushes the schedule to the device (redundant with #1)
   and the app reads it.

A cloud-commit failure logs a warning but the device is still updated via MQTT.

### Service usage
```yaml
service: anker_solix.modify_solix_use_time
target:
  entity_id: select.<device>_pps_usage_mode
data:
  slots:
    - {tariff: 1, start_time: "00:00", end_time: "08:00"}
    - {tariff: 2, start_time: "08:00", end_time: "09:00"}
    - {tariff: 3, start_time: "09:00", end_time: "24:00"}
```
tariff: 1=Peak, 2=Mid, 3=Off. 1–6 slots, contiguous, covering 00:00–24:00. The `slots` field
is PPS-only; SB2 AC devices use the existing seasonal fields (start_month/end_month/day_type/
start_hour/end_hour/tariff/tariff_price/delete) and ignore `slots`. Dispatch: entity feature
`TOU_SCHEDULE` (16) → PPS path; `AC_CHARGE` (8) → SB2 path. `required_features` is
`[AC_CHARGE, TOU_SCHEDULE]` (OR-matched), so the service is offered on both entity types.

### PR scope: A1763 only
This PR addresses **A1763 (SOLIX C1000 Gen 2) only** — the only model with captured,
byte-verified evidence. The author's `pps_tou_schedule` command is shared across models, and
per-model field maps gate the behavior:

| Model | `0090` `pps_tou_schedule` mapping | Status |
|---|---|---|
| A1763 (C1000 G2) | `CMD_TOU_PLAN_FULL_V2` (this PR: `fe` timestamp, count in `a6`, `counted=False`) | **byte-verified** |
| AS220 (S2000) | `CMD_TOU_PLAN_V2` (author's: `fd` ms timestamp, count inline in `a7`) | author's baseline, unchanged |
| A1765 / A1783 / A1785 | none | not in this PR; `set_tou_schedule` logs "Command not supported" (graceful, no crash) |

The author's `pps_tou_schedule: MODELS` feature flag (previously commented out with
"# TODO: Enable once fully supported") is enabled; models without a `0090` mapping fail
gracefully. A1765/A1783/A1785 are untouched in the diff so the author can review the single
A1763 mapping and extend to the family as appropriate.

### Files changed (all in `custom_components/anker_solix/`)

**MQTT path (device control):**
- `mqttcmdmap.py`: new shared constant `CMD_TOU_PLAN_FULL_V2` (full-state `0090`, `fe`
  unix-seconds timestamp, count in the separate `a6` field, `counted=False`), documented as
  A1763-verified. The author's `CMD_TOU_PLAN_V2` (AS220) is unchanged.
- `mqttmap.py`: A1763 `0090` group maps `pps_tou_schedule` → `CMD_TOU_PLAN_FULL_V2` (plus the
  `pps_usage_mode` + `backup_soc` partial commands); plus `005e` and the variable-length
  `0421.d9`. A1765/A1783/A1785 are untouched.
- `mqtt_pps.py`: `set_tou_schedule` builds the full-state `0090` exactly as the app sends it.

**Cloud path (app-visible store):**
- `mqtt_pps.py`: `set_tou_schedule` reads the cloud `pps_use_time` **once**; the `0090` backup
  SOC comes from the **device cache** (the user's latest choice via the `pps_backup_soc`
  number) so a TOU write does not silently change the backup SOC, with the cloud's
  `reserve_power` as fallback only when the device cache has no value. The read is reused for
  the commit (no extra API call). A cloud read/commit failure no longer blocks the device
  `0090`.
- `mqtt_pps.py`: `_commit_tou_to_cloud` reads the current `pps_use_time` (or reuses an
  already-read dict via its `base` arg), replaces its `ranges` with the new schedule
  (preserving `prices`/`unit`/`reserve_power`), and writes it back via the maintainer's existing
  `get_device_attributes` / `set_device_attributes` (no new REST code).
- `mqtt_pps.py`: `update_tou_plan_presets` now returns the device-reported `active_tariff`
  (0421.d9[0]) as `{"preset_tariff": N}` (TODO removed).
- `apitypes.py`: endpoint comments document the `pps_use_time` attribute.
- `examples/Mqtt_C1000_Gen2/device_attrs_*.json`: `pps_use_time` added to the A1763 fixture so
  the cloud-commit path is covered in testmode.

**Service/entity (consolidated on the author's existing surface):**
- `services.py` + `services.yaml`: `modify_solix_use_time` extended — `required_features`
  `[AC_CHARGE, TOU_SCHEDULE]` (OR), new optional `slots` field, frontend filter on both
  `BACKUP` (8) and `RELEASE_NOTES` (16). No new service.
- `select.py`: the `pps_usage_mode` select gains the `TOU_SCHEDULE` feature (16); the
  `modify_solix_use_time` dispatcher sub-branches on the entity feature (PPS →
  `set_tou_schedule`, SB2 → `set_sb2_use_time`).
- `entity.py`: `TOU_SCHEDULE = 16` feature flag.
- `const.py`: `slots` merged into `SOLIX_USE_TIME_SCHEMA` (1–6 slots, tariff 1/2/3, HH:MM
  0–24); `TOU_SLOTS`/`VALID_TOU_HOUR` constants.
- `helpers.py`: `convert_pps_tou_schedule` gains the `counted` parameter.

### Verified
- syntax + map validation pass on all changed files;
- the `pps_tou_schedule` (`CMD_TOU_PLAN_FULL_V2`) command reproduces the app's `0090`
  byte-for-byte (fields `a2/a5/a6/a7/fe`);
- the cloud round-trip (read → modify → write → re-read) is stable and preserves
  `prices`/`unit`/`reserve_power`;
- mock full-flow test (3 cases: device-SOC-preserved, cloud-fallback, cloud-read-failure)
  passes;
- live round-trip test on the living-room unit (A1763) of the **final** code path: the
  off-peak window was shifted +1h (09–19 → 10–20) and then shifted back (10–20 → 09–19).
  Both directions applied to **both** the device (entity `tou_mode_schedule`) and the cloud
  store (`pps_use_time`) within ~15s, and `prices`/`unit`/`reserve_power` were preserved.
  This closed the last open item (§7).
- **Root cause of an earlier "success but no change":** the `a6` (slot-count) field of
  `CMD_TOU_PLAN_FULL_V2` initially had no value range and a `STATE_CONVERTER` that only
  handled the schedule dict. `run_command` validates each parameter via
  `validate_cmd_value`, which calls the converter as `converter(None, <int>, cache)` and then
  range-checks the result — with no `VALUE_MIN/MAX` the `MqttCmdValidator` raised
  ("Expected range or options definition!"), so `a6` failed validation, `run_command`
  returned `None` **silently**, and the service still reported success. Fixed by giving `a6`
  a real 1–6 range and making the converter pass explicit ints through. The 0090 byte format
  was correct all along (byte-verified above); only the in-process validation was broken.

### Note for testmode
The cloud read/commit uses `toFile` like the rest of the API. The A1763 `device_attrs` example
now includes `pps_use_time`, so testmode runs exercise the full cloud path. If a different
fixture is used without `pps_use_time`, the cloud read falls back gracefully (empty base,
device-cache backup SOC) and the commit logs a warning while the MQTT device update still applies.

---

## 3. Feature status table

| Feature | Read (state) | Write (control) | Status |
|---|---|---|---|
| **Usage mode** (UPS ↔ TOU) | ✅ `usage_mode` from `0421.d9` | ✅ `pps_usage_mode` select → `0090.a2` | **Complete** |
| **Active tariff** | ✅ `active_tariff` from `0421.d9` (device-reported) | — (informational) | **Complete (read)** |
| **TOU schedule** (≤6 slots) | ✅ `tou_mode_schedule` from `0421.d9` | ✅ **NEW** `modify_solix_use_time` (`slots` field) → full-state `0090` + cloud `pps_use_time` commit | **Complete (read + write, end-to-end)** |
| **Backup SOC / "TOU power"** | ✅ `backup_soc` from `0421.d9` | ✅ `pps_backup_soc` number → `0090.a5` | **Complete** |
| **Storm guard switch** | ✅ `storm_guard_switch` from `0421.d9` | ✅ `pps_storm_guard_switch` → `005e.a5` | **Complete** |
| **Backup plan window** | ✅ `backup_start/end_timestamp` from `0421.d9` + `0425` echo | ✅ `modify_solix_backup_charge` service → `005e` | **Complete** |

Headline wins:
1. **TOU schedule is now settable from HA end-to-end** (device + app) via
   `modify_solix_use_time` with the `slots` field — the user's core feature, consolidated on
   the author's existing service rather than a parallel one.
2. **All backup/TOU state now has readback** from the corrected variable-length `0421.d9`
   (backup_soc, storm_guard, backup plan timestamps, active tariff) — previously these
   entities had no state.

---

## 4. MQTT protocol reference (A1763)

### 4.1 Message-type map

**`dt` (telemetry) types**

| Type | Size | Confirmed meaning |
|------|------|-------------------|
| `0421` | 46 fields | Main status. Contains the `d9` TOU/backup block (variable-length). |
| `0900` | — | Identical structure to `0421` (alternate status publish). |
| `0425` | 31 B | **Backup-plan status echo** — readback for the `005e` command. `a3`=start ts, `a4`=end ts (`0xffffffff`=ongoing, `0`=cleared). |
| `0503` | 47 B | **Statistics/energy** — rare (~1 per 11 h/unit) and NOT command-triggerable (`0057` does not prompt it). `a2`=6×u32 LE cumulative energy counters (Wh), `a3`=4-byte unix-seconds timestamp. Correlates with the cloud's "estimated savings" (`energy × price` — real arithmetic in §4.7; mechanism not validated). Per-counter semantics inferred, not confirmed. Not mapped. |
| `0857` | 14 B | **ACK** for `0057` (realtime trigger). `a1=0x32`. |
| `085e` | 14 B | **ACK** for `005e` (backup plan). `a1=0x32`. |
| `0889` | 52 B | **Response** to `0089` (time sync). `a1..a6` small values, `fd`=16-byte buffer with ASCII ms-timestamp (device clock). |
| `0890` | 14 B | **ACK** for `0090` (TOU). `a1=0x32`. |
| `0891` | 14 B | Periodic heartbeat. `a1=0x32`. |
| `0892` | 36 B | Diagnostics. `a1=0x34`, `a2`=16 B (zeros + trailing `00 00 00 7f`), `a3=0x04`. Constant across all samples — no actionable state, not mapped. |
| `0901` | 14 B | Periodic heartbeat. `a1=0x32`. |
| `0902` | 14 B | Periodic heartbeat. `a1=0x32`. |
| `0903` | 14 B | Periodic heartbeat. `a1=0x32`. |

**ACK scheme (confirmed, 100% time-correlation):** the device response type is
`0x0800 | cmd_type`. Verified `0057→0857` (103/103), `005e→085e` (22/22),
`0090→0890` (13/13), `0089→0889` (6/6). The `0891`/`0901`/`0902`/`0903` heartbeats carry no
actionable state (constant `a1=0x32`) and are not mapped.

**`cmd` (app command) types**

| Type | Confirmed meaning |
|------|-------------------|
| `0040` | Status request. `a1=0x22` (cmd code), `fe`=request timestamp. |
| `0100` | Status request with params. `a1=0x22`, `a2=0100031700`, `fe`=timestamp. |
| `0057` | Realtime trigger. |
| `005e` | Backup charge plan (see §4.3). |
| `0089` | Time sync. `a1=0x22`, `a2`=4-byte unix timestamp. |
| `0090` | TOU (usage mode + backup SOC + schedule, see §4.2). |
| `0101` | AC command group. |
| `0102` | DC command group. |

Common command fields: `a1=0x22` (command code), `fe`/`fd` = message timestamp.

### 4.2 `0090` — usage mode + backup SOC + TOU schedule

Full schedule save (captured 12:31:13, 6-slot):
```
a1=0x22  a2=01  a5=0x33  a6=06  a7=01000a020a0b030b0c020c0d030d13011318  fe=<ts>
```
- `a2` usage mode: 0 = Standard (UPS), 1 = Time-of-Use.
- `a3`/`a4` = plan id / reserved. The app sends `a3=00`, `a4=00` (both 2-byte `01 00`).
- `a5` backup SOC % ("TOU power" in the app). Captured `0x33`=51.
- `a6` TOU slot count (equals number of slots in `a7`). **Max 6 slots** (confirmed: user set a
  6-slot schedule, `a6=06`).
- `a7` TOU slots, **NO leading count byte** (differs from AS220/A1785):
  `(tariff, start_hr, end_hr) × N`, tariff 1=Peak, 2=Mid, 3=Off.
  6-slot capture: (1,0,10)(2,10,11)(3,11,12)(2,12,13)(3,13,19)(1,19,24).
- `fe` = 4-byte unix-seconds LE timestamp (see §1.3).
- Usage-mode-only toggle sends **only `a2`** (no a5/a6/a7). The device merges partial `0090`
  updates (a mode-only toggle works without touching a5/a6/a7).

**Verified live:** sending the fixed `0090` to the living-room unit → device ACKs (`0890`) and
re-publishes `0421` with the new schedule (restored 5-slot → 3-slot, PASS).

### 4.3 `005e` — backup charge plan

Matches the A1783/A1785/AS220 layout (the author's existing `CMD_BACKUP_*_V2` definitions
reused verbatim — the A1763 `005e` group is a copy of the author's A1783 group):
- `a3` plan id (0x03 = backup plan)
- `a4` backup plan switch (0/1)
- `a5` storm guard switch (0/1)
- `a6` plan-timestamps mode (0/1/2)
- `a7` 10 bytes: `(max_soc, min_soc, start_ts[4B LE], end_ts[4B LE])`; `end=0xffffffff` = ongoing.
- `a8`/`fe` = timestamps (second plan block / message ts).

**Readback confirmed:** `0425` (status echo) returns the applied plan (a3=start, a4=end), and
the live `0421.d9` block reflects the switches (see §4.4). Correlated: `005e a4=0,a5=1` →
`d9` backup_switch=1, status=1; `a4=0,a5=0` → status=0; `a4=1,a5=0` → storm_guard=0;
`a6=2` → status=2.

### 4.4 `0421.d9` — TOU/backup state block (VARIABLE-LENGTH)

**Critical correction:** `d9` is variable-length. The TOU schedule region is
`(1 count byte + 3 bytes/slot × count)`, so every field after the schedule shifts with the
slot count. Total length = `25 + 3×count` bytes (confirmed for count=3→34 B, 4→37 B, 6→43 B
across all 5 units). The map uses a sequential `BYTES` list so the parser advances past the
variable-length schedule.

```
off  meaning (confirmed)
00   active_tariff  — tariff active at the message time: 0=none (UPS), 1=Peak, 2=Mid, 3=Off
01   usage_mode     — 0=Standard, 1=Time-of-Use
02   backup_soc     — backup reserve % ("TOU power"), = 0090.a5
03   max_soc        — 100
04   min_soc        — 1
05   tou_slot_count — number of slots that follow
06.. tou_slots      — (tariff, start_hr, end_hr) × count  (== 0090.a7, byte-for-byte)
+0   backup_status  — 0=inactive, 1=planned charge, 2=storm-guard charge
+1   backup_switch  — 0/1
+2   storm_guard    — 0/1
+3.. backup_start_timestamp    (u32 LE; 0 = none)
+7.. backup_end_timestamp      (u32 LE; 0xffffffff = ongoing)
+11. auto_backup_start_timestamp
+15. auto_backup_end_timestamp
```
(offsets `+0..+15` are relative to the end of the slot region)

**Verified:**
- `active_tariff` (d9[0]) matches the tariff computed from the schedule + message time for
  **778/778** TOU-mode status messages (0 mismatches). This is the "currently active tariff"
  the device reports directly.
- `usage_mode`/`active_tariff` flip in lockstep at the exact usage-mode toggle instants
  (the user's observed "TOU System Status 0→3" transition).
- `d9` TOU slots (`d9[6..]`) equal the `0090.a7` command bytes exactly.
- `backup_soc`/`storm_guard`/`backup_status` reflect the `005e` commands (correlated above).
- Office unit (715) shows `backup_status=2, storm_guard=1` while its fast-charge plan is active.

### 4.5 `convert_pps_tou_schedule` — `counted` parameter
- `counted=True` (default): leading slot-count byte — used by the author's `CMD_TOU_PLAN_V2`
  (AS220; the author's comment also lists A1785, which has no `0090` mapping in this PR) and by
  the A1763 `0421.d9` status field (the bin field starts at the count byte, so it is included).
  Behavior unchanged.
- `counted=False`: bare `(tariff, start_hr, end_hr)` triplets read until the field bytes are
  exhausted — used by the A1763 `0090` command `a7`, where the count lives in the separate
  `a6` field (the app always sends exactly `count×3` bytes, so read-until-exhausted is
  equivalent to reading exactly `a6` triplets).
Empirical check (real `convert_pps_tou_schedule`, both directions, on the captured app
`a7 = 010009030913011318` — the user's live 3-slot schedule):

| Mode | Decode captured `a7` | Encode the live 3-slot schedule |
|---|---|---|
| `counted=False` | 3 slots: 00-09 t1, 09-19 t3, 19-24 t1 ✓ | `010009030913011318` (9 B) — **byte-exact** ✓ |
| `counted=True` | 1 garbage slot (tariff=0, 09→03) — misreads `0x01` as count=1 ✗ | `03010009030913011318` (10 B) — not byte-exact ✗ |

So `a7` is unambiguously bare triplets with the count in `a6`; the 5-slot capture behaves
identically (`counted=False` → `01000a030a0b020b0d030d13011318` 15 B byte-exact; `counted=True`
would prepend `0x05`). The AS220 format is unaffected.

### 4.6 Unmapped `0421` fields (documentation-only, not user-actionable)
- `a1` = constant `0x34` (status byte) on all 5 units.
- `dc` = 6 zero bytes (reserved).
- `fa` = 21-byte device-info/firmware-build id: `01 01 01 01 00 XX 03 00 …00`, where
  `XX=0x1f` for fw 1.1.2.6 and `0x17` for fw 1.1.4.1.

### 4.7 `0503` — statistics / energy counters (investigated; savings correlation noted, mechanism not validated)

`0503` is a **telemetry statistics report** the device publishes to the cloud. Structure:
- `a1` = `0x12` (constant).
- `a2` = **6 × u32 LE** cumulative energy counters (unit = Wh, based on magnitude).
- `a3` = 4-byte unix-seconds timestamp (verified: matches the message time to the minute).

Observed values (living room, 2026-08-29 12:17):
```
u32[0]=0          u32[1]=305,287  (~305 kWh)   u32[2]=279,996  (~280 kWh)
u32[3]=17,406,070 (~17.4 MWh)     u32[4]=0                    u32[5]=10,261,130 (~10.3 MWh)
```

**What is confirmed (from captures):**
- The counters are **energy** (Wh). Magnitudes are consistent with a C1000 (~1 kWh battery,
  full daily discharge → hundreds of kWh/month, ~10 MWh lifetime).
- `u32[0]` and `u32[4]` read **0** on the living-room unit. The user's interpretation is the
  **DC in/out port** counters (the DC ports are unused on every unit) — consistent with the
  zeros, but inference, not confirmed.
- `0503` is **not command-triggerable** — a `0057` realtime trigger was tested and produces
  only `0421`/`0900`/`0857`/`0889`, never `0503`. The
  `charging_energy_service/energy_statistics` REST endpoint returns all-zero for standalone
  PPS (empty `site_id`), so it cannot supply the named values either.

**Real-evidence correlation with the app's "estimated savings"** (every number below is from
an on-disk capture; the correlation is real, the *mechanism* behind it is not validated):

| Source | Value |
|---|---|
| `get_device_income` → `history_income` (2026-08-29) | living room `3,830.1` (captured mid-currency-test with `curve_unit=Kč`, same underlying value the app shows as ~$3,830); office `$2,674.8` (`curve_unit=$`); unnamed `~$19` (user-reported, not in captures) |
| `pps_use_time` → `prices` (current) | $0.20 / $0.05 / $0.001 |
| Living-room `0503` largest counter (`u32[3]`) | 17,406 kWh |

Arithmetic on those numbers:
- `17,406 kWh × $0.20 ≈ $3,481` ≈ living room's `3,830` (~9% low).
- `17,406 kWh × $0.001 ≈ $17.4` ≈ the unnamed unit's `~$19`.
- `19 / 3800 = 0.005` = `0.001 / 0.20` (the low:high price ratio).

These are **consistent with** the app's "estimated savings" being a function of
`(energy × price)`. They do **not** establish the mechanism — which counter feeds it, how the
cloud composites it, or at what cadence are not observable from the captures. (Context,
user-reported: 4 of the 5 units ran with a too-high $/kWh price setting before it was
corrected on all 5, which is why their savings accumulated higher; the pre-correction config
was not captured.)

**Forward test (prices now corrected on all 5, not yet observed):** if savings is
`energy × price`, the 5 units' savings should now increment roughly in **lockstep** (same
price, similar daily energy); a unit that keeps diverging would indicate a per-unit energy
difference, not a price one.

**What is NOT confirmed (would need a same-unit time series):**
- Which counter is which tariff tier (peak/mid/off) vs charge/discharge/import/export, or
  which counter feeds the savings figure. The two captured `0503` samples are from
  **different** units (bedroom + living), so a cross-unit "delta" is not a valid time series.
- Any cloud-side compositing step or its cadence. The observed `0503` telemetry cadence is
  ~1 per 11 h/unit, but that is the report rate, not evidence of a compositing step.


**Not mapped** in the integration (no user-actionable entity); documented for completeness.
To confirm per-counter semantics, capture `0503` from the **same** unit at two times (≥ hours
apart) and correlate the deltas against the app's per-category energy (or a controlled charge
during a known tariff window).

---

## 5. Currency / price (REST, not MQTT)

The user found a currency dropdown in the app. This is a **server-side REST setting**, not an
MQTT signal: it changes the `curve_unit` in `get_device_income` (observed flip `$` → `Kč`). It
is not in `device_attrs` and the setter requires a station/site id that is empty in this
account (no "power site"). Candidate endpoints: `get_currency_list` (works, 14 currencies),
`adjust_station_price_unit` / `get_site_price` (need a station id). **Not part of the MQTT
integration**; documented for completeness. (The per-tariff `prices`/`unit` for the TOU plan
live in the `pps_use_time` cloud store, §1.2.)

---

## 6. Resolved & remaining items

**Resolved this pass:**

1. ✅ **`update_tou_plan_presets`** — now returns the device-reported `active_tariff`
   (`0421.d9[0]`) as `{"preset_tariff": N}` (0=none, 1=Peak, 2=Mid, 3=Off). TODO removed.
   (Still not wired to a select entity — the active tariff is already directly exposed via the
   `active_tariff` field; the method is available if a derived option is wanted.)
2. ✅ **`005e.a8` purpose — proven** from captured app commands: `a8` is a 4-byte unix-seconds
   timestamp (equal to `fe`) when `a6=0`/`a6=1` (no second plan), and a full 10-byte second
   plan block `(max_soc, min_soc, start_ts, end_ts)` when `a6=2` (two-plan mode).
3. ✅ **Test fixture** — `pps_use_time` added to the A1763 `device_attrs` example
   (`Mqtt_C1000_Gen2/device_attrs_6WPYSCSCKOX3F770I.json`), so the cloud-commit path is
   covered in testmode.
4. ✅ **`reserve_power`/`backup_soc` sync** — `set_tou_schedule` reads the cloud `pps_use_time`
   once; the `0090` backup SOC comes from the **device cache** (the user's latest choice via the
   `pps_backup_soc` number) so a TOU write does not silently change the backup SOC, with the
   cloud's `reserve_power` as fallback only when the device cache has no value. The read is
   reused for the commit (no extra API call). A cloud read/commit failure no longer blocks the
   device `0090`. Also fixed a latent read bug (the cloud `pps_use_time` is nested under
   `data.attributes`, not the top level).
5. ✅ **Consolidation on the author's existing surface** — the parallel `set_solix_tou_schedule`
   service and `pps_tou_full` command were removed. The TOU schedule is now set through the
   author's existing `modify_solix_use_time` service (new optional `slots` field; PPS/SB2
   dispatch on the entity feature) and the author's existing `pps_tou_schedule` command (A1763
   mapped to the new shared `CMD_TOU_PLAN_FULL_V2` constant). The author's
   `pps_tou_schedule: MODELS` feature flag (previously commented out) is enabled. See §2.
6. ✅ **Live end-to-end round-trip on the final code path** — on the living-room A1763, the
   off-peak window was shifted +1h (09–19 → 10–20) and back (10–20 → 09–19) through the
   `modify_solix_use_time` `slots` service. Both directions applied to the device (entity
   `tou_mode_schedule`) **and** the cloud (`pps_use_time`) within ~15s; `prices`/`unit`/
   `reserve_power` preserved. This also exposed and fixed the `a6` validation bug (see §2
   "Verified"): the 0090 bytes were correct, but the in-process `a6` range/converter made
   `run_command` fail silently while the service reported success.

**Still open (best-effort documented):**

7. **`0503` (statistics) per-counter semantics** — confirmed as 6×u32 Wh energy counters.
   The app's "estimated savings" **correlates** with `energy × price` on real captured
   numbers (17,406 kWh × $0.20 ≈ $3,481 ≈ observed $3,830; × $0.001 ≈ $17.4 ≈ ~$19; and
   19/3800 = 0.005 = the `0.001/0.20` price ratio), but the **compositing mechanism is not
   validated** (which counter, and how/when the cloud composites it, are not observable).
   What remains unconfirmed is **which counter is which tariff/flow** and any cloud-side
   compositing step (needs a same-unit time series; `0503` is rare and not command-
   triggerable). See §4.7. `0892` (diagnostics) is constant across samples — no actionable
   state, not mapped.

8. **`pps_backup_soc` number entity does not commit to the cloud** — setting the backup SOC via
   the `pps_backup_soc` number sends `0090.a5` to the device only. `set_tou_schedule` now
   re-syncs the cloud from the device on the next TOU write, but a dedicated commit in the
   number's set path (or reading `reserve_power` for the number's state) would keep them in sync
   continuously.

---

## 7. PR validation matrix (per piece)

| Piece | Evidence | Strength |
|---|---|---|
| `0090` TOU command (A1763) | 19 captured app commands; built command field-identical (`a2/a5/a6/a7/fe`) | Strong |
| `005e` backup-charge (A1763) | 29 captured app commands decode cleanly through the mapping; the mapping is a verbatim copy of the author's A1783 `005e` group (their `CMD_BACKUP_*_V2` constants, unchanged) | Strong |
| `0421.d9` restructure | All 5 units decode with valid, internally-consistent values (per-unit schedules, `active_tariff`, one unit showing a real `backup_status=2`/`storm_guard_switch=1` event); decoded with the current mapping | Good |
| `set_tou_schedule` flow | 3 mock cases (device-SOC-preserved, cloud-fallback, cloud-read-failure) | Mock |
| Cloud commit (`pps_use_time`) | Mock + fixture; preserves `prices`/`unit`/`reserve_power`, replaces `ranges` | Mock |
| `active_tariff` preset | `0421 d9[0]` decode (778/778 correlation, §4.4) | Strong |
| Live round-trip (final code) | Living-room A1763: off-peak shifted +1h (09–19→10–20) and back (10–20→09–19) via `modify_solix_use_time` `slots`; both directions applied to device (entity `tou_mode_schedule`) **and** cloud (`pps_use_time`) within ~15s; `prices`/`unit`/`reserve_power` preserved | **Live** |

**Gaps (known, non-blocking):**
1. **Raw `0421` bytes are not retained** — the captured `0421` files are decoded dumps (no raw
   field), so the `d9` verification rests on prior-session captures decoded with the current
   mapping. A fresh passive raw capture (device status push, no API calls) would close this.
2. **`0890`/`085e` ACK captures are empty placeholders** — the device ACKs to `0090`/`005e`
   were never saved (the `0890`/`085e` files contain `{}`). The app commands + `0421` state
   confirm the commands took effect, but no raw device-ACK bytes are retained.
3. **~~Live end-to-end re-run after the consolidation~~ — RESOLVED** — the final code path was
    exercised live on the living-room A1763 (off-peak shifted +1h and back, both directions
    verified on device + cloud, §6 item 6 / matrix above).