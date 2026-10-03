# OpenSmell Exchange Format v1.0

Every contributed recording consists of **one CSV file** and **one metadata JSON file**.

## CSV file

- Name: `{substance}_{device_id}_{session_date}.csv`
- **substance** must be a single word. Use hyphens for spaces: `green-tea`, `brussel-sprouts`.
- Example: `coffee_esp32-mq3_2026-06-15.csv`

### Required columns

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | float (**seconds**) | Time since recording start. Strongly recommended — see below. |
| `sensor_1` through `sensor_N` | float | Sensor readings. N can be any number ≥ 1. |

If a recording has a `timestamp` column, it **must** be in seconds and must be
monotonically non-decreasing. There is no unit tag in the column name, so a file
timestamped in milliseconds is indistinguishable from a 1000× rate error. Declare
the rate in `sampling_rate_hz` so consumers can check the two against each other.

Column names can be descriptive (e.g., `sensor_NO2`, `sensor_alcohol`) or generic (`sensor_1`). The upload tool auto-detects sensor columns by checking for one of three accepted prefixes (matching the data-commons Rust crate):
- `sensor_` — e.g., `sensor_1`, `sensor_NO2`
- `MQ` — e.g., `MQ-135`, `MQ3`
- `ch` — e.g., `ch0`, `ch1` (generic channel-numbered columns)

### Rules

- No header rows other than the column names on line 1.
- Use comma separators. Decimal point is `.`.
- Readings should be raw (uncalibrated) sensor outputs.
- The file can contain any number of rows (≥ 10).
- Sampling rate must be recorded in the metadata as `sampling_rate_hz` (see
  below). A CSV without a timestamp column and without a declared rate cannot be
  used for any time-domain feature and will be flagged `no_time_axis`.

### Declaring sampling rate

Add `sampling_rate_hz` to the metadata JSON — the nominal rate your firmware was
built with. OpenSmell firmwares emit it at boot on the serial stream:

```
INFO,universal-esp32,1.0.0,6,interval_ms=500
```

which declares 2 Hz. Consumers should prefer the measured median gap between
consecutive timestamps over the declared value, and should report
`flags.time_unit_mismatch` when the two disagree by more than 2×, because that
almost always means a time-unit error rather than real jitter. Full rationale and
the ingestion plausibility gate are in `electronic-nose/SAMPLING_CONTRACT.md`,
which is the single source of truth for cadence across the project.

## Metadata JSON file

Same base name as the CSV: `coffee_esp32-mq3_2026-06-15.json`

```json
{
  "substance": "coffee",
  "device_id": "esp32-mq3",
  "session_date": "2026-06-15",
  "contributor": "your-name (optional)",
  "sensor_info": {
    "sensor_1": "MQ-135 (VOC)",
    "sensor_2": "MQ-3 (Alcohol)",
    "sensor_3": "MiCS-6814 (CO/NO2)"
  },
  "sampling_rate_hz": 2.0,
  "notes": "Room temperature ~22°C. Sample placed 2cm from sensor inlet."
}
```

`sensor_info` is optional but strongly recommended — it helps the global model align different hardware.

`sampling_rate_hz` is required for any recording intended for kinetic or
drift analysis. Sampling rate is a device constant alongside $V_{cc}$, $R_L$, and
$R_0$: every temporal feature divides a sample count by this number, so an
omitted rate rescales rise time, decay time, latency, and hysteresis by the same
factor.

### Optional: phase events

Add an `events` list to the metadata JSON to label phases within a recording.
This matters for anything measured during a change rather than at a steady
state — exposures, air gaps, recovery — because a consumer who has to infer the
phase boundaries from the response is inferring them from the thing being
measured.

```json
{
  "events": [
    {"label": "baseline",    "start_ms": 0,      "end_ms": 300000},
    {"label": "exposure_a",  "start_ms": 300000, "end_ms": 360000},
    {"label": "gap",         "start_ms": 360000, "end_ms": 960000},
    {"label": "exposure_b",  "start_ms": 960000, "end_ms": 1020000},
    {"label": "recovery",    "start_ms": 1020000}
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `label` | string | Phase name. Free-form; the validator only warns about unconventional names. |
| `start_ms` | number | Phase start, **milliseconds** from recording start. `start_s` is also accepted. |
| `end_ms` | number | Optional phase end, same unit. Omit for the final phase. |

Conventional labels are `baseline`, `exposure_a`, `exposure_b`, `gap`, and
`recovery`. Any other label is accepted — an experiment may need one the
validator has never seen — but non-standard labels are reported so a consumer can
see the vocabulary is local to the contributor.

Note the unit asymmetry: `timestamp` in the CSV is in **seconds**, while
`start_ms`/`end_ms` are in **milliseconds**. This is a deliberate belt-and-braces
choice rather than an oversight — the two sit next to each other, and a
millisecond file is otherwise indistinguishable from a 1000× rate error, so a
unit-tagged key is the only thing that makes the mix-up visible. `start_s` and
`end_s` exist for contributors who prefer to match the CSV's units. The validator
flags a ~1000× disagreement between the event span and the recording span in
either direction.

Events must not overlap, and an event must not end before it starts. The validator
also reports whether event boundaries fall on a sample edge: at 2 Hz a boundary
up to one 500 ms period off the grid is ordinary quantisation, and more than that
means the boundary was estimated rather than observed. That distinction matters
because an estimated transition time carries an error of the same order as the
fast recovery mode (τ ≈ 8–25 s).

The same structure is written as a standalone `events.json` inside `.osmell`
bundles (`opensmell`, `SessionEvent`), so a bundle converted from an exchange
submission keeps its phase labels.

### Sensor metadata (required in metadata JSON)

For every sensor column, the metadata JSON must specify:

- `unit`: What physical quantity the column represents. One of:
  - `resistance_ohm` — raw resistance in ohms
  - `voltage` — voltage from a divider circuit
  - `rs_r0` — ratio Rs/R0 (baseline-corrected resistance)
  - `adc` — raw analog-to-digital converter counts
- `sensor_model` — e.g., "MQ-135", "MiCS-6814", "SGP30", "BME680"
- `circuit` — brief description (e.g., "voltage divider with 10kΩ load resistor at 5V")

If temperature and humidity were recorded, include them as additional sensor columns with:
- `unit: temperature_celsius`
- `unit: humidity_percent`

Example updated metadata.json:
```json
{
  "substance": "coffee",
  "device_id": "esp32-mq3",
  "session_date": "2026-06-15",
  "contributor": "your-name",
  "sensor_info": {
    "sensor_1": "MQ-135 (VOC)",
    "sensor_2": "MQ-3 (Alcohol)",
    "sensor_3": "MiCS-6814 (CO/NO2)"
  },
  "sensor_units": {
    "sensor_1": "rs_r0",
    "sensor_2": "rs_r0",
    "sensor_3": "rs_r0"
  },
  "sensor_models": {
    "sensor_1": "MQ-135",
    "sensor_2": "MQ-3",
    "sensor_3": "MiCS-6814"
  },
  "circuit": "Voltage divider with 10kΩ load resistors at 5V. ESP32 ADC reads 0-4095.",
  "sampling_rate_hz": 2.0,
  "temperature_celsius": 22.0,
  "humidity_percent": 55.0,
  "notes": "Sample placed 2cm from sensor inlet."
}
```

## Directory structure

```
my_recordings/
├── coffee_esp32-mq3_2026-06-15.csv
├── coffee_esp32-mq3_2026-06-15.json
├── vanilla_esp32-mq3_2026-06-15.csv
└── vanilla_esp32-mq3_2026-06-15.json
```