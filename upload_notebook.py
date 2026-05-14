# OpenSmell Data Commons — Upload Script
# --------------------------------------
# Run this in Colab or locally. It reads a folder of CSV+JSON pairs,
# validates them, and uploads to opensmell/community on HuggingFace.

import os, json, glob
import pandas as pd
from datasets import Dataset, load_dataset
from huggingface_hub import login

# ----- CONFIG -----
HF_DATASET = "opensmell/community"
DATA_DIR = "./my_contributions"   # folder with your CSV+JSON pairs
# ------------------

# Authenticate (Colab: use secrets; locally: run `huggingface-cli login` first)
try:
    from google.colab import auth
    auth.authenticate_user()
except:
    pass  # running locally
login()

def validate_and_load(data_dir):
    """Scan folder, validate CSVs, return list of dicts ready for Dataset."""
    records = []
    csv_files = glob.glob(os.path.join(data_dir, "*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")

    for csv_path in csv_files:
        base = os.path.splitext(csv_path)[0]
        json_path = base + ".json"
        fname = os.path.basename(csv_path)

        # Parse filename: substance_deviceID_date.csv
        # Substance must not contain underscores (use hyphens for spaces).
        parts = os.path.splitext(fname)[0].split("_")
        if len(parts) < 3:
            print(f"⚠️  Skipping {fname}: filename must be substance_device_date (3+ parts)")
            continue
        substance = parts[0]
        device_id = parts[1]
        session_date = parts[2]

        # Load CSV
        try:
            df = pd.read_csv(csv_path)
        except Exception as e:
            print(f"⚠️  Skipping {fname}: CSV read error — {e}")
            continue

        if len(df) < 10:
            print(f"⚠️  Skipping {fname}: too few rows ({len(df)})")
            continue

        # Find sensor columns
        sensor_cols = [c for c in df.columns if c.lower().startswith("sensor")]
        if not sensor_cols:
            # fallback: if no sensor_ prefix, take all numeric columns except timestamp
            sensor_cols = df.select_dtypes(include="number").columns.tolist()
            if "timestamp" in sensor_cols:
                sensor_cols.remove("timestamp")
        if not sensor_cols:
            print(f"⚠️  Skipping {fname}: no sensor columns found")
            continue

        # Load metadata
        metadata = {}
        if os.path.exists(json_path):
            with open(json_path) as f:
                try:
                    metadata = json.load(f)
                except:
                    print(f"⚠️  Could not parse {os.path.basename(json_path)}")

        # Build record
        record = {
            "filename": fname,
            "substance": substance,
            "device_id": device_id,
            "session_date": session_date,
            "sensor_count": len(sensor_cols),
            "num_rows": len(df),
            "csv_data": df.to_csv(index=False),   # store as string
            "metadata": json.dumps(metadata),
        }
        records.append(record)
        print(f"✅ {fname} — {len(sensor_cols)} sensors, {len(df)} rows")

    return records

# Run validation
records = validate_and_load(DATA_DIR)
print(f"\n{len(records)} valid recordings found")

if records:
    dataset = Dataset.from_list(records)
    # Try to load existing dataset, append, then push
    try:
        existing = load_dataset(HF_DATASET, split="train")
        from datasets import concatenate_datasets
        dataset = concatenate_datasets([existing, dataset])
        print(f"Merged with existing dataset. Total: {len(dataset)} recordings")
    except:
        print("Creating new dataset on HuggingFace")

    dataset.push_to_hub(HF_DATASET)
    print(f"✅ Uploaded to {HF_DATASET}")
else:
    print("❌ No valid recordings to upload.")