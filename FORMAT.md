# OpenSmell Exchange Format v1.0

Every contributed recording consists of **one CSV file** and **one metadata JSON file**.

## CSV file

- Name: `{substance}_{device_id}_{session_date}.csv`
- **substance** must be a single word. Use hyphens for spaces: `green-tea`, `brussel-sprouts`.
- Example: `coffee_esp32-mq3_2026-06-15.csv`

### Required columns

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | float (seconds) | Optional. Time since recording start. |
| `sensor_1` through `sensor_N` | float | Sensor readings. N can be any number ≥ 1. |

Column names can be descriptive (e.g., `sensor_NO2`, `sensor_alcohol`) or generic (`sensor_1`). The upload tool auto-detects sensor columns by checking for the `sensor_` prefix.

### Rules

- No header rows other than the column names on line 1.
- Use comma separators. Decimal point is `.`.
- Readings should be raw (uncalibrated) sensor outputs.
- The file can contain any number of rows (≥ 10).

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
  "notes": "Room temperature ~22°C. Sample placed 2cm from sensor inlet."
}
```

`sensor_info` is optional but strongly recommended — it helps the global model align different hardware.

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