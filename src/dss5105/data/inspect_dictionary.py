import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DICT_FILE = PROJECT_ROOT / "output-final-delivery" / "field_dictionary_v1.json"


with open(DICT_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)


print(f"Top-level type: {type(data).__name__}")
print(f"Number of records: {len(data)}")


if isinstance(data, list):

    print("\n=== Keys found in first record ===")

    if data:
        print(list(data[0].keys()))

    print("\n=== Field dictionary records ===")

    for i, item in enumerate(data, start=1):

        print(f"\n--- Record {i} ---")

        if isinstance(item, dict):
            for key, value in item.items():
                print(f"{key}: {value}")
        else:
            print(item)