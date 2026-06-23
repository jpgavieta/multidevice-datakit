import pandas as pd

from src.etl.parsers import atmotube
from src.etl.parsers import ponyopi

# This should work REGARDLESS of the extract data method (read files or call apis)

# Logic is all based on device_type, looping over each device_id within it.

# ============================================================================================================
# Device Registry
# Maps the "device_type" (top-level key) to the specific parser module

DEVICE_REGISTRY = {
    "Atmotube": atmotube,
    "Ponyopi": ponyopi,
}

# ============================================================================================================
# Pure Transformation Logic

def transform_device_data(
    raw_data: dict[str, dict[str, pd.DataFrame]]
) -> dict[str, dict[str, dict]]:
    """
    Applies device-specific parsers to raw DataFrames, one device_id at a time.

    IMPORTANT: parsing happens per device_id, never on combined/concatenated
    data. Some files are JSON-blob format, others pre-flattened — each
    parser auto-detects that from its own single input, so every device_id
    must be parsed independently or that detection breaks.

    Parameters
    ----------
    raw_data : dict
        { device_type: { device_id: raw_df } } — output of extract.py

    Returns
    -------
    dict
        { device_type: { device_id: { "data": { df_name: { "df": <DataFrame>: {...} } } } } 
        Example: {'Atmotube': {'C3CBE16AE294_01-May-2026_12-Jun-2026': {'data': {'gis': {'df': <DataFrame> } } } } } 
    """
    results: dict[str, dict[str, dict]] = {}

    for device_type, device_files in raw_data.items():
        if device_type not in DEVICE_REGISTRY:
            print(f"⚠️ No parser registered for device '{device_type}'. Skipping.")
            continue

        parser_module = DEVICE_REGISTRY[device_type]
        results[device_type] = {}

        for device_id, raw_df in device_files.items():
            try:
                # Apply the parser (Transform Step) — one device_id at a time
                parsed_result = parser_module.parse(raw_df)

                results[device_type][device_id] = { 
                    "data": {
                        key: { # this turns it 
                            "df": df,
                            # "cols": [col for col in df.columns if col != "datetime"] # i dont think this is being used anywhere else? seems unnecessary shit to me
                        }
                        for key, df in parsed_result.items()
                    }
                }
                print(f"✅ Transformed {device_type}/{device_id}")

            except Exception as e:
                print(f"❌ Transformation failed for {device_type}/{device_id}: {e}")

    return results
# Example: transformed = transform_device_data(raw_data)
#          transformed["Atmotube"]["C3CBE16AE294_01-May-2026_12-Jun-2026"]["data"]["pm"]["df"]     # PM DataFrame for that device_id
#          transformed["Atmotube"]["C3CBE16AE294_01-May-2026_12-Jun-2026"]["data"]["pm"]["cols"]    # ['pm2_5_ugm3_atm', 'pm10_ugm3_atm', ...]
#          transformed["Atmotube"]["C3CBE16AE294_01-May-2026_12-Jun-2026"]["gis"]                   # GIS DataFrame for that device_id

