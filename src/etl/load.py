from src.etl.extract import extract_raw_data
from src.etl.transform import transform_device_data


# This orchestrates extract and transform ->  returns data ready for the visualization

# Each device_type is its own stream; within it, each
#       device_id (physical device / file) stays separate rather than being
#       merged together, so every row stays traceable back to its source file.

# ============================================================================================================

def load(mount_path: str) -> dict:
    """
    Run the full extract -> transform pipeline for all device_type folders
    under mount_path.

    Parameters
    ----------
    mount_path : str
        Root folder containing one subfolder per device_type.

    Returns
    -------
    dict
        { device_type: { device_id: { "gis": df, "data": { table_name: {"df":, "cols":} } } } }
    """
    raw_data = extract_raw_data(mount_path)
    return transform_device_data(raw_data)

# Example: data = load("/home/yul/mnt/proton-data")
#          data["Atmotube"]["C3CBE16AE294_01-May-2026_12-Jun-2026"]["data"]["pm"]["df"]    # PM DataFrame for that device_id
#          data["Atmotube"]["C3CBE16AE294_01-May-2026_12-Jun-2026"]["gis"]                 # GIS DataFrame for that device_id
#          list(data["Atmotube"].keys())                                                   # all device_ids loaded for Atmotube

if __name__ == "__main__":
    MOUNT_PATH = "/home/yul/mnt/proton-data"
    data = load(MOUNT_PATH)
    if data:
        print(f"\nLoaded {len(data)} device_type stream(s).")
        for device_type, devices in data.items():
            print(f"   {device_type}: {len(devices)} device_id(s) -> {list(devices.keys())}")
        print()
        # display_loaded_data(data)