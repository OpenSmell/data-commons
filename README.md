# OpenSmell Data Commons

Submission, verification, and approval pipeline for shared e-nose data.

> **Repo split:** this GitHub `data-commons` repo holds behaviors, schemas, and
> the reference `sensor_constants.json` (constant data). The Hugging Face repo
> `opensmell/data-commons` holds **only user-uploaded community recordings** —
> never constants, schemas, or this repository's internals.

## Constant data

`sensor_constants.json` is the canonical reference copy of the MOX power-law
constants (SDK convention `rr = a·C^b`, `C` in ppm, `rr = R/R0`), derived from
datasheet tables and mirrored from the authoritative embedded copy at
`opensmell/opensmell/constants/sensors.json`. It is a **reference only** and is
never uploaded to the Hugging Face community-data repo.

## Overview

The data-commons crate provides a quality-gated pipeline for contributing labeled sensor data to a shared repository. Every submission is scored on five dimensions, hashed for integrity, and routed through auto-verification or human approval.

## Architecture

```
data-commons/src/
  lib.rs  — Contribution, Metadata, QualityScorer, VerificationPipeline
```

```
commons_data/
  pending/    — submissions awaiting human review
  approved/   — verified contributions (auto or manual)
```

## Quality Scoring

Every contribution receives a score from 0-100:

| Metric | Weight | What It Measures |
|--------|--------|------------------|
| Signal quality | 30 | SNR per channel, noise floor |
| Baseline stability | 25 | First 20% vs last 20% drift |
| Metadata completeness | 20 | Substance, device, date, sensor info, notes |
| Session duration | 15 | 100-1000 samples optimal |
| Novelty | 10 | How different from existing contributions |

**Threshold:** 60/100 minimum for auto-approval. Below 60 goes to human review.

### Signal Quality Scoring

SNR computed per channel:
```
SNR = mean_signal / std_noise
```
Normalized to 0-1 range using empirical distribution of past contributions.

### Baseline Stability Scoring

Compares first 20% vs last 20% of recording:
```
drift = abs(mean(first_20%) - mean(last_20%)) / mean(first_20%)
```
Drift < 5% = 1.0, drift > 50% = 0.0, linear interpolation between.

### Metadata Completeness

```
substance:   0.25 weight (required)
device_id:   0.25 weight (required)
session_date: 0.25 weight (required)
sensor_info: 0.15 weight (sensor models, units)
notes:       0.10 weight (free-text description)
```

### Session Duration

```
100-1000 samples: 1.0 (optimal)
50-99 samples:    0.7 (acceptable)
10-49 samples:    0.3 (minimal)
<10 samples:      0.0 (insufficient)
```

### Novelty

Compares contribution hash against existing approved contributions. New substances, devices, or sensor configurations score higher.

## Usage

### Submit a Contribution

```rust
use data_commons::{VerificationPipeline, Metadata};
use std::path::Path;

let pipeline = VerificationPipeline::new(Path::new("./commons_data"));

let contribution = pipeline.submit(
    Path::new("session_2024_01_15.csv"),
    Path::new("metadata.json"),
)?;

println!("Quality score: {:.1}/100", contribution.quality_score);
println!("Status: {:?}", contribution.status);
```

### Metadata Format (JSON)

```json
{
  "substance": "ethanol",
  "device_id": "opensmell-001",
  "session_date": "2024-01-15",
  "contributor": "research-lab-a",
  "sensor_info": {
    "ch0": "MQ-3",
    "ch1": "MQ-135",
    "ch2": "MQ-7",
    "ch3": "MQ-8"
  },
  "sensor_units": {
    "ch0": "ppm",
    "ch1": "ppm"
  },
  "sensor_models": {
    "ch0": "Winsen MQ-3",
    "ch1": "Winsen MQ-135"
  },
  "notes": "Controlled lab exposure, 100ppm ethanol vapor",
  "temperature_celsius": 22.5,
  "humidity_percent": 45.0
}
```

### CSV Format

```csv
timestamp,ch0,ch1,ch2,ch3
0.0,1024,2048,512,768
0.1,1025,2050,511,770
0.2,1023,2047,513,767
```

- First column: timestamp (seconds from session start)
- Remaining columns: ADC readings per channel
- No header row required; auto-detected

### Approval Workflow

```rust
// List pending submissions
let pending = pipeline.list_pending()?;
for c in &pending {
    println!("{}: score {:.1}, substance: {}", c.id, c.quality_score, c.substance);
}

// Approve (human review)
let approved = pipeline.approve(&contribution.id)?;
assert_eq!(approved.status, ContributionStatus::Approved);
```

### Auto-Verification

If quality score >= 60, contribution is automatically approved:
```
ContributionStatus::AutoVerified
```

If score < 60:
```
ContributionStatus::Pending  → human review required
```

### Rejection

```rust
// Rejection with reason
let rejected = Contribution {
    status: ContributionStatus::Rejected("Insufficient signal quality".into()),
    ..contribution
};
```

## Data Integrity

Every contribution receives a SHA-256 hash of the CSV content:

```rust
let hash = contribution.id; // SHA-256 hex string
```

Verified on submission. Rejected if hash doesn't match file content.

## File Structure

```
commons_data/
  pending/
    {hash}.json    — Contribution metadata (pending review)
  approved/
    {hash}.json    — Contribution metadata (approved)
    {hash}.csv     — Raw sensor data
```

## Dependencies

```toml
opensmell = { path = "../opensmell-rs" }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
csv = "1"
chrono = "0.4"
thiserror = "1"
log = "0.4"
sha2 = "0.10"
```

## Testing

```bash
cargo test -p data-commons    # Run all 2 tests
```

Tests validate:
1. Quality scoring accuracy (signal quality, baseline stability, metadata completeness, duration)
2. Submission and approval workflow (hash generation, file routing, status transitions)
