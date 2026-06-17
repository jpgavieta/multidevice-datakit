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
        { device_type: { device_id: { "gis": df, "data": { table_name: {...} } } } }
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

                # Standardize output structure
                results[device_type][device_id] = {
                    "gis": parsed_result.get("gis"),
                    "data": {
                        key: {
                            "df": df,
                            "vars": [col for col in df.columns if col != "datetime"]
                        }
                        for key, df in parsed_result.items()
                        if key not in ("gis", "all")
                    }
                }
                print(f"✅ Transformed {device_type}/{device_id}")

            except Exception as e:
                print(f"❌ Transformation failed for {device_type}/{device_id}: {e}")

    return results

# Example: transformed = transform_device_data(raw_data)
#          transformed["Atmotube"]["C3CBE16AE294_01-May-2026_12-Jun-2026"]["data"]["pm"]["df"]     # PM DataFrame for that device_id
#          transformed["Atmotube"]["C3CBE16AE294_01-May-2026_12-Jun-2026"]["data"]["pm"]["vars"]    # ['pm2_5_ugm3_atm', 'pm10_ugm3_atm', ...]
#          transformed["Atmotube"]["C3CBE16AE294_01-May-2026_12-Jun-2026"]["gis"]                   # GIS DataFrame for that device_id


def clean_data_dict(processed_data: dict, selected: dict[str, list[str]]) -> dict:
    """
    NOTE: still written for the OLD shape ({device_type: {"gis":..., "data":...}})
    and needs an extra device_id loop before it matches the new nested output
    of transform_device_data above. Left as-is rather than guessed at, since
    whether cleaning should run per device_id independently or pooled across
    all of a device_type's device_ids is a real design decision, not just a
    mechanical fix.

    Cleans data for ALL devices based on selected columns.
    """
    cleaned_all = {}
    all_selected_cols = [col for cols in selected.values() for col in cols]

    if not all_selected_cols:
        return processed_data

    for device_name, device_content in processed_data.items():
        merged = None
        for df_key, cols in selected.items():
            if not cols or df_key not in device_content["data"]:
                continue
            df = device_content["data"][df_key]["df"][["datetime"] + cols]
            merged = df if merged is None else pd.merge(merged, df, on="datetime", how="outer")

        if merged is None:
            cleaned_all[device_name] = device_content
            continue

        valid_datetimes = set(merged.dropna(subset=all_selected_cols)["datetime"])
        cleaned_folder = {}

        for df_key, contents in device_content["data"].items():
            df = contents["df"]
            clean_df = df[df["datetime"].isin(valid_datetimes)].copy()
            clean_df = clean_df.dropna()
            cleaned_folder[df_key] = { "df": clean_df, "vars": contents["vars"] }

        cleaned_all[device_name] = { "gis": device_content["gis"], "data": cleaned_folder }

    return cleaned_all

# Example: not yet compatible with transform_device_data's 3-level output (see note above) —
#          needs an added device_id loop before this can run against {device_type: {device_id: {...}}}.