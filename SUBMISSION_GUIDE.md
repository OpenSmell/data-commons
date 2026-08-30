# OpenSmell Data Commons — Submission Guide

## How to Contribute Data

### 1. Record Data with Osmograph

Record your sessions using the Osmograph desktop app. The app automatically saves:
- Raw sensor CSV data
- Metadata (device info, session notes, calibration status)

### 2. Prepare Your Submission

Create a directory with your recordings:

```
my_submission/
├── coffee_esp32-mq3_2026-08-20.csv
├── coffee_esp32-mq3_2026-08-20.json
├── tea_esp32-mq3_2026-08-20.csv
└── tea_esp32-mq3_2026-08-20.json
```

### 3. Validate Your Submission

```bash
python validate_submission.py my_submission/
```

Fix any errors before submitting.

### 4. Submit

**Option A: GitHub Pull Request (preferred)**
1. Fork the data-commons repository
2. Add your files to `submissions/<your-name>/`
3. Create a pull request

**Option B: Direct submission**
1. Zip your directory
2. Email to: submissions@opensmell.org
3. Include your name and affiliation

### 5. Verification Process

Your submission goes through:

1. **Automated validation** (FORMAT.md compliance)
2. **Quality scoring** (signal quality, baseline stability, noise floor)
3. **Human review** (sanity check, metadata completeness)
4. **Approval** (added to the public commons)

Timeline: 1-3 business days for automated + human review.

## What We're Looking For

### Good Submissions
- Multiple sessions of the same substance (for baseline learning)
- Clear metadata (what substance, what device, what conditions)
- Diverse conditions (different temperatures, humidity levels)
- Novel substances not already in the commons

### Bad Submissions
- Too few samples (< 10 rows)
- Missing metadata
- Unclear substance identification
- Duplicate data already in the commons

## Data License

Contributions are released under CC-BY-4.0. You retain credit; the community benefits.

## Quality Scoring

Each submission receives a quality score (0-100):

| Factor | Weight | Description |
|--------|--------|-------------|
| Signal quality | 30% | SNR, noise floor, saturation |
| Baseline stability | 25% | R0 variance, drift rate |
| Metadata completeness | 20% | All required fields present |
| Session duration | 15% | Longer = better for baseline learning |
| Novelty | 10% | New substance or condition not in commons |

Minimum quality for acceptance: 60/100.

## Tracking

After approval, your contribution is assigned a DOI and cited in all papers that use it.

## Questions?

Open an issue on GitHub or email: community@opensmell.org
