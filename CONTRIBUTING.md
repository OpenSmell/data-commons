# Contribute to OpenSmell Data Commons

The OpenSmell project needs labeled electronic nose recordings from as many devices as possible. Your contribution helps build the world's first universal e-nose standard.

## What you need

- An electronic nose (any hardware — 2 sensors, 6 sensors, 16 sensors, anything).
- 10–20 common household smell items (coffee, lemon, vanilla extract, cinnamon, etc.).
- A way to save sensor readings as a CSV file (see the [format spec](FORMAT.md)).

## How to contribute

1. **Record** — For each substance, hold your e-nose over the sample for 60 seconds. Save one CSV file per substance per session.
2. **Name** — Use the pattern `substance_deviceID_date.csv` (e.g., `coffee_esp32_2026-06-15.csv`). Use hyphens for multi-word substances: `green-tea_esp32_2026-06-15.csv`.
3. **Describe** — Create a small JSON file with the same name, describing your sensors and any notes.
4. **Upload** — Run our [Colab upload notebook](upload_notebook.py) to push your data to `opensmell/opensmell`.

## Why contribute?

- Your name (or pseudonym) will appear in the dataset's contributor list.
- You'll help make electronic noses interoperable — a genuinely open standard.
- Early contributors get early access to the global calibration model.

## Need hardware?

We're working on a reference e-nose design. Join our [Discord](https://discord.gg/CGER3tHxbH) for updates.

## Questions?

Discord or open a GitHub issue on `opensmell/data-commons`.