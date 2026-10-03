# OSM Serial Protocol Specification

> **Canonical source.** This copy lives in `data-commons` and is versioned
> there. The readable hub is `OpenSmell/docs/`.

Communication protocol between OpenSmell devices and host software.

## Overview

The OpenSmell Serial Message (OSM) protocol is a lightweight, line-based protocol for transmitting sensor data, device metadata, calibration events, and errors over serial (USB) or TCP connections.

## Physical Layer

### Serial (USB)

- **Baud rate:** 115200
- **Data bits:** 8
- **Stop bits:** 1
- **Parity:** None
- **Flow control:** None

### TCP (WiFi)

- **Port:** 8080
- **Connection:** One persistent connection per device
- **Discovery:** mDNS service `_osmograph._tcp`

## Message Format

All messages are newline-terminated ASCII strings. No binary encoding.

```
MESSAGE_TYPE,<field1>,<field2>,...,<fieldN>\n
```

## Message Types

### Data — `OSM`

Transmitted at the device's declared interval (see `INFO`), nominally every 500 ms
(2 Hz). The rate is **not** implied by the protocol and must not be assumed by the
host; read it from `INFO,<...>,interval_ms=<MS>`. A host that assumes a rate will
silently rescale every temporal feature by the ratio between the assumed and true
rates — rise time, decay time, latency, and AUC all divide a sample count by it.

```
OSM,<adc0>,<adc1>,...,<adcN>
```

| Field | Type | Description |
|-------|------|-------------|
| `adc0..adcN` | float | ADC reading per sensor channel |

**Example (6-channel device):**
```
OSM,1024.50,2048.30,512.10,768.90,384.20,1280.70
```

**Parsing rules:**
- Channels auto-padded/truncated to expected count
- Non-numeric values skipped
- Timestamp assigned by host on receipt

### Info — `INFO`

Transmitted once on connection and on PING response.

```
INFO,<device_id>,<firmware_version>,<n_sensors>[,interval_ms=<MS>]
```

| Field | Type | Description |
|-------|------|-------------|
| `device_id` | string | Unique device identifier |
| `firmware_version` | string | Semver format (e.g., `1.2.3`) |
| `n_sensors` | integer | Number of active sensor channels |
| `interval_ms` | integer | **Optional, but a host that lacks it is guessing.** Nominal sample period in milliseconds. |

**Example:**
```
INFO,opensmell-001,1.2.3,6,interval_ms=500
```

`samplingRateHz` is a device constant alongside `Vcc`, `R_L`, and `R0`. A host
receiving an `INFO` line without `interval_ms` should record the stream's rate as
unknown rather than defaulting it, and should prefer the measured median gap
between line arrivals when timestamps are available — measured cadence beats
declared cadence. See `electronic-nose/SAMPLING_CONTRACT.md`.

### Calibration — `CAL`

Transmitted when baseline R0 is established or updated.

```
CAL,<channel>,<r0_value>
```

| Field | Type | Description |
|-------|------|-------------|
| `channel` | integer | Sensor channel index (0-based) |
| `r0_value` | float | Baseline resistance (ADC counts) |

**Example:**
```
CAL,0,1024.50
CAL,1,2048.30
```

### Error — `ERR`

Transmitted on hardware or software errors.

```
ERR,<code>,<message>
```

| Field | Type | Description |
|-------|------|-------------|
| `code` | integer | Error code (see table below) |
| `message` | string | Human-readable description |

**Error codes:**

| Code | Meaning |
|------|---------|
| 1 | ADC read failure |
| 2 | Sensor not responding |
| 3 | Calibration incomplete |
| 4 | Memory overflow |
| 5 | WiFi connection lost |
| 6 | Fan failure |
| 7 | Temperature/humidity sensor failure |

**Example:**
```
ERR,2,Sensor MQ-135 not responding on channel 1
```

### Ping — `PING`

Heartbeat transmitted every 5 seconds. Host responds with `INFO`.

```
PING
```

### Response — `PONG`

Host sends in response to PING (optional, for latency measurement).

```
PONG,<host_timestamp>
```

## Timing

| Event | Interval | Notes |
|-------|----------|-------|
| Data transmission | Declared via `INFO` (`interval_ms`), nominally 500 ms / 2 Hz | Continuous after connection |
| Ping | 5s | Device-initiated |
| Calibration | On event | 30 min baseline at startup |
| Error | On event | Immediate |

## Connection Sequence

```
1. Host opens serial/TCP connection
2. Device sends INFO (device ID, firmware, sensor count, sample interval)
3. Host records the declared interval; if absent, the rate is unknown until it can
   be measured from line arrival times
4. Device enters baseline collection (30 min)
5. During baseline: CAL messages sent every 5 min
6. After baseline: OSM messages at the declared interval
7. Host sends PING every 5s
8. Device responds with INFO on PING
```

## Calibration Sequence

```
1. Device powers on
2. Enters baseline mode (30 min in clean air)
3. Collects ADC readings at the declared interval (nominally 500 ms / 2 Hz)
4. After 30 min: computes R0 (median of first 15%)
5. Sends CAL,<channel>,<r0> for each channel
6. Transitions to normal operation (OSM messages)
```

## Cartridge Swap Protocol

```
1. Host detects cartridge swap (user action or scheduled)
2. Host sends: SWAP,<channel>,<new_cartridge_id>
3. Device responds: CAL,<channel>,<new_r0> after recalibration
4. Device logs: INFO,Cartridge swap channel <ch> <old> -> <new>
```

## Arduino Firmware

The `generate_arduino_sketch()` function produces a complete `.ino` file:

```rust
let sketch = generate_arduino_sketch(
    sensor_pins=&[32, 33, 34, 35, 36, 39],
    wifi_ssid="OpenSmell-Dev",
    wifi_password="password123",
);
```

**Generated firmware includes:**
- WiFi connection with mDNS (`_osmograph._tcp`)
- TCP server on port 8080
- ADC sampling at `PRINT_INTERVAL` (nominally 500 ms / 2 Hz; see the generated
  `SAMPLE_INTERVAL_MS` and the `interval_ms` field on the `INFO` line)
- 30-second baseline collection (configurable)
- OSM protocol output
- PING/PONG heartbeat
- Error handling (ERR messages)
- EEPROM persistence for calibration data

## Host Software Requirements

### Minimum

1. Open serial/TCP connection
2. Parse OSM lines → `SensorReading`
3. Accumulate baseline (first 15% of samples)
4. Normalize readings: `(Rs - R0) / R0`
5. Extract features
6. Detect anomalies

### Production

1. All minimum requirements
2. Adaptive threshold calibration
3. Fail-safe system (3 redundant detectors)
4. User labeling integration
5. Session recording and export
6. Data-commons submission
7. Fleet management (multiple devices)

## Parser Implementation

```rust
use opensmell::{OsmProtocol, OsmMessage};

let protocol = OsmProtocol::new(expected_channels=6);

// Parse incoming serial line
let line = "OSM,1024.50,2048.30,512.10,768.90,384.20,1280.70";
let timestamp = 1234567890.0; // host timestamp

match protocol.parse_line(line, timestamp)? {
    OsmMessage::Data { channels, timestamp } => {
        assert_eq!(channels.len(), 6);
        // channels[0] = 1024.50, channels[1] = 2048.30, ...
    }
    OsmMessage::Info { device_id, firmware_version, n_sensors } => {
        // Register device in fleet
    }
    OsmMessage::Calibration { channel, r0_value } => {
        // Update baseline for channel
    }
    OsmMessage::Error { code, message } => {
        // Handle error, alert user
    }
    OsmMessage::Ping => {
        // Respond with PONG
    }
    OsmMessage::Unknown(raw) => {
        // Log and skip
    }
}
```

## Error Handling

- **Parse errors:** Skip line, log warning, continue
- **Channel mismatch:** Auto-pad with 0.0 or truncate to expected count
- **Timeout:** No data for 10s → warning; 30s → reconnect
- **CRC errors:** Not implemented (TCP provides integrity)
- **Buffer overflow:** Device sends ERR,4 and resets buffer

## Extensions

### Future: Binary Protocol

For high-throughput applications (>100 Hz), a binary protocol may be added:

```
[0xAA][0x55][type:1][length:2][payload:N][checksum:1]
```

Not implemented in v0. At the nominal 500 ms interval an ASCII line of six ADC
values is far below the 115200 baud link budget, so the protocol is not the
bottleneck. It would become one above roughly 100 Hz.
