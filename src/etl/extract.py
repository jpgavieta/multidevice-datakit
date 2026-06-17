import os
import csv
import pandas as pd

# This should stay device-agnostic: reads files now, will fetch from APIs later.

# Logic is based on device_type (top-level folder), device_id (filename) underneath.

# ============================================================================================================

def _expected_col_count(file_path: str) -> int:
    """Reads just the header row to determine the expected number of columns."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        header_line = f.readline()
    return len(next(csv.reader([header_line])))


def _make_bad_line_fixer(expected_cols: int):
    """
    Returns a closure for pandas' on_bad_lines: if a row has more fields
    than the header, merge the overflow back into the last column.
    """
    def fix_bad_line(bad_line):
        if len(bad_line) > expected_cols:
            correct_part = bad_line[: expected_cols - 1]
            merged_last = ",".join(bad_line[expected_cols - 1:])
            correct_part.append(merged_last)
            return correct_part
        return bad_line
    return fix_bad_line


def extract_raw_data(mount_path: str) -> dict[str, dict[str, pd.DataFrame]]:
    """
    Scans device_type folders under mount_path and loads each CSV as its
    own raw DataFrame, keyed by device_id (filename without extension).

    Each device_id is kept SEPARATE on purpose — device-type parsers expect
    to run on one device_id's file at a time. Some files are JSON-blob
    format, others pre-flattened; concatenating them before parsing would
    corrupt column auto-detection in the parser.

    Parameters
    ----------
    mount_path : str
        Root folder containing one subfolder per device_type
        (e.g. "Atmotube", "Ponyopi", "Fitbit").

    Returns
    -------
    dict
        { device_type: { device_id: raw_df } }
    """
    if not os.path.exists(mount_path):
        print(f"❌ Path not found: {mount_path}")
        return {}

    all_data: dict[str, dict[str, pd.DataFrame]] = {}
    print(f"--- Scanning: {mount_path} ---")

    for device_type in os.listdir(mount_path):
        folder_path = os.path.join(mount_path, device_type)
        if not os.path.isdir(folder_path):
            continue

        print(f"Processing folder: {device_type}")
        device_files: dict[str, pd.DataFrame] = {}

        for file_name in os.listdir(folder_path):
            if not file_name.endswith(".csv"):
                continue

            device_id = os.path.splitext(file_name)[0]
            file_path = os.path.join(folder_path, file_name)

            try:
                expected_cols = _expected_col_count(file_path)
                fix_bad_line = _make_bad_line_fixer(expected_cols)

                df = pd.read_csv(
                    file_path,
                    engine="python",
                    on_bad_lines=fix_bad_line,  # merges overflow fields dynamically
                    skipinitialspace=True,
                )
                device_files[device_id] = df
                print(f"   ✅ Loaded {device_id}: {df.shape}")

            except Exception as e:
                print(f"   ❌ Failed {file_name}: {e}")

        if device_files:
            all_data[device_type] = device_files
            print(f"  ✅ {device_type}: {len(device_files)} device_id(s) loaded")
        else:
            print(f"  ⚠️ {device_type}: No valid CSVs loaded")

    return all_data

# Example: data = extract_raw_data("/home/yul/mnt/proton-data")
#          data.keys()                                                    # dict_keys(['Atmotube', 'Ponyopi', 'Fitbit'])
#          data["Atmotube"].keys()                                        # dict_keys(['C3CBE16AE294_01-May-2026_12-Jun-2026', ...])
#          data["Atmotube"]["C3CBE16AE294_01-May-2026_12-Jun-2026"]       # raw DataFrame for that device_id


if __name__ == "__main__":
    MOUNT_PATH = "/home/yul/mnt/proton-data"
    data = extract_raw_data(MOUNT_PATH)
    if data:
        print(f"\n🚀 Success! Loaded {len(data)} device_type folder(s).")
        for device_type, files in data.items():
            print(f"   {device_type}: {list(files.keys())}")