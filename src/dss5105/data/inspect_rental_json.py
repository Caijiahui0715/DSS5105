import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_FILE = PROJECT_ROOT / "output-final-delivery" / "rental_data_v1.json"


with open(DATA_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

print("Top-level type:", type(data).__name__)

if isinstance(data, dict):
    print("Top-level keys:", list(data.keys()))

    for key, value in data.items():
        print(f"\n=== {key} ===")
        print("Type:", type(value).__name__)

        if isinstance(value, list):
            print("Count:", len(value))
            if value:
                print("First record keys:", list(value[0].keys()))
                print("First record:", value[0])
        else:
            print(value)