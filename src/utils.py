import re

import json
import pandas as pd 

from functools import reduce
from tzfpy import get_tz

from typing import Any, Dict, Optional

# ============================================================================================================
# JSON-blob-in-CSV Data

def safe_json_loads(s):
    """Safely parse JSON string; returns empty dict on failure."""
    try:
        return json.loads(s) if pd.notna(s) else {}
    except (json.JSONDecodeError, TypeError):
        return {}

def flatten_dict(d, parent_key='', sep='.'):
    """Recursively flatten nested dictionaries."""
    items = {}
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(flatten_dict(v, new_key, sep=sep))
        else:
            items[new_key] = v
    return items

def detect_json_col(df, sample_size=100):
    for col in df.columns:
        if df[col].dtype not in ['object', 'string']:
            continue
        sample = df[col].dropna().head(sample_size)
        if len(sample) == 0:
            continue
        json_count = 0
        for val in sample:
            if not isinstance(val, str):
                val = str(val)
            val = val.strip()
            if len(val) >= 2:
                if (val.startswith('"') and val.endswith('"')) or \
                (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1].strip()
            if val.startswith('{') or val.startswith('['):
                try:
                    json.loads(val)
                    json_count += 1
                except (json.JSONDecodeError, TypeError):
                    pass
        if json_count > (len(sample) * 0.5): # threshold: at least 50% of sampled values should parse as JSON
            return col
    return None

def parse_jsonblob_csv(df, json_col=None, keep_original_cols=None):
    """
    Process DataFrame with a JSON blob column: auto-detects the JSON column,
    flattens it, and keeps all other original columns.
    """
    df = df.copy()

    # 1. Auto-detect JSON column
    if json_col is None:
        json_col = detect_json_col(df)
        if json_col is None:
            raise ValueError("No JSON column detected. Please specify 'json_col' manually.")
        print(f"Auto-detected JSON column: '{json_col}'")

    # 2. Validate JSON column exists
    if json_col not in df.columns:
        raise KeyError(f"Column '{json_col}' not found. Available: {list(df.columns)}")

    # 3. Set default for keeping original columns
    if keep_original_cols is None:
        # Keep all columns except the JSON column being flattened
        keep_original_cols = [col for col in df.columns if col != json_col]
    else:
        # Validate user-specified columns exist
        missing = [c for c in keep_original_cols if c not in df.columns]
        if missing:
            raise KeyError(f"Columns {missing} not found in DataFrame.")

    # 4. Parse JSON
    df[json_col] = df[json_col].apply(safe_json_loads)

    # 5. Flatten JSON and keep original columns
    # Create a list of DataFrames to concatenate
    dfs_to_concat = []

    # 6. Add the original non-JSON columns
    if keep_original_cols:
        dfs_to_concat.append(df[keep_original_cols].reset_index(drop=True))

    # 7. Add the flattened JSON columns
    flattened_data = []
    for _, row in df.iterrows():
        flattened_data.append(flatten_dict(row[json_col]))
    flattened_df = pd.DataFrame(flattened_data)
    dfs_to_concat.append(flattened_df)

    # 8. Combine everything
    final_df = pd.concat(dfs_to_concat, axis=1)
    return final_df   

# Example: parse_jsonblob_csv(raw_df) # auto-detects JSON column and keeps all other columns by default


# ============================================================================================================
# GIS Df Builder 
    # Uses UTC datetime + lat + lon columns

def detect_utc_col(df, sample_size=50):
    """
    Detect all datetime-like columns, rank them by legitimacy,
    rename the best one to 'datetime', and move it to the first column.
    Returns the updated DataFrame and the detected column name.
    """
    utc_pattern = re.compile(
        r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}'
    )
    tz_aware_pattern = re.compile(
        r'(\+\d{2}:\d{2}|Z|UTC)$'
    )
    name_keywords = ['time', 'date', 'datetime', 'timestamp', 'ts']

    candidates = {}

    for col in df.columns:
        score = 0
        col_lower = col.lower()

        if any(kw in col_lower for kw in name_keywords):
            score += 1

        if df[col].dtype not in ['object', 'string']:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                score += 5
                score += df[col].notna().mean()
                candidates[col] = score
            continue

        sample = df[col].dropna().head(sample_size)
        if len(sample) == 0:
            continue

        iso_matches = sum(1 for v in sample if utc_pattern.match(str(v).strip()))
        tz_matches  = sum(1 for v in sample if tz_aware_pattern.search(str(v).strip()))
        fill_rate   = df[col].notna().mean()

        if iso_matches == 0:
            continue

        score += (iso_matches / len(sample)) * 3
        score += (tz_matches  / len(sample)) * 2
        score += fill_rate

        candidates[col] = score

    if not candidates:
        return df, None

    best_col = max(candidates, key=candidates.get)

    df = df.rename(columns={best_col: 'datetime'})
    cols = ['datetime'] + [c for c in df.columns if c != 'datetime']
    df = df[cols]

    print(f"Detected datetime column: '{best_col}' (score: {candidates[best_col]:.2f}) → renamed to 'datetime'")

    return df, best_col

# Example: df, col = detect_utc_col(df) # standalone --> auto-detects, renames, reorders, included in add_timezone_col()


def detect_latlon_cols(df, sample_size=50):
    """
    Detect latitude and longitude columns by name keywords AND valid geographic range.
    Renames detected columns to 'latitude' and 'longitude' for standardization.
    Returns updated DataFrame and (lat_col, lon_col).
    """
    lat_keywords = ['lat', 'latitude']
    lon_keywords = ['lon', 'lng', 'longitude']

    lat_candidates = {}
    lon_candidates = {}

    for col in df.columns:
        col_lower = col.lower()

        if not pd.api.types.is_numeric_dtype(df[col]):
            continue

        sample = df[col].dropna().head(sample_size)
        if len(sample) == 0:
            continue

        col_min, col_max = sample.min(), sample.max()

        if any(kw in col_lower for kw in lat_keywords):
            if -90 <= col_min and col_max <= 90:
                lat_candidates[col] = 4

        if any(kw in col_lower for kw in lon_keywords):
            if -180 <= col_min and col_max <= 180:
                lon_candidates[col] = 4

    lat_col = max(lat_candidates, key=lat_candidates.get) if lat_candidates else None
    lon_col = max(lon_candidates, key=lon_candidates.get) if lon_candidates else None

    rename_map = {}
    if lat_col and lat_col != 'latitude':
        rename_map[lat_col] = 'latitude'
        print(f"Detected lat column: '{lat_col}' → renamed to 'latitude'")
    elif lat_col:
        print(f"Detected lat column: '{lat_col}'")

    if lon_col and lon_col != 'longitude':
        rename_map[lon_col] = 'longitude'
        print(f"Detected lon column: '{lon_col}' → renamed to 'longitude'")
    elif lon_col:
        print(f"Detected lon column: '{lon_col}'")

    if not lat_col or not lon_col:
        print("Warning: Could not detect lat/lon columns — timezone will default to UTC.")

    df = df.rename(columns=rename_map)

    return df, 'latitude' if lat_col else None, 'longitude' if lon_col else None

def add_timezone_col(df, datetime_col=None, lat_col=None, lon_col=None):
    """
    Add timezone column but keep datetime in UTC.
    Calls detect_utc_col and detect_latlon_cols internally if columns not specified.
    Timezone is only assigned to rows with valid coordinates — rows with missing
    lat/lon are left as NaN.
    Returns DataFrame with columns reordered: datetime, longitude, latitude, timezone first.
    """
    df = df.copy()

    # 1. Auto-detect and standardize datetime column
    if datetime_col is None:
        df, datetime_col = detect_utc_col(df)
        if datetime_col is None:
            raise ValueError("No UTC datetime column detected. Please specify 'datetime_col' manually.")

    # 2. Auto-detect and standardize lat/lon columns
    if lat_col is None or lon_col is None:
        df, lat_col, lon_col = detect_latlon_cols(df)

    # 3. Ensure datetime is UTC-aware
    df['datetime'] = pd.to_datetime(df['datetime'], utc=True)

    # 4. Identify valid coordinates — exclude NaN and 0.0, 0.0 (null island)
    if lat_col and lon_col:
        valid_coords = (
            df[lat_col].notna() & df[lon_col].notna() &
            (df[lat_col] != 0.0) & (df[lon_col] != 0.0)
        )
    else:
        valid_coords = pd.Series(False, index=df.index)

    # 5. Add timezone column — only for rows with valid coordinates, NaN otherwise
    df['timezone'] = pd.NA
    if valid_coords.any():
        df.loc[valid_coords, 'timezone'] = df.loc[valid_coords].apply(
            lambda row: get_tz(lng=row[lon_col], lat=row[lat_col]),
            axis=1
        )

    # 6. Reorder: datetime, longitude, latitude, timezone first
    priority_cols = [c for c in ['datetime', 'longitude', 'latitude', 'timezone'] if c in df.columns]
    remaining_cols = [c for c in df.columns if c not in priority_cols]
    df = df[priority_cols + remaining_cols]

    return df
# Example: df = add_timezone_col(df)                                                             # fully auto-detected
#          df = add_timezone_col(df, lat_col='latitude', lon_col='longitude')                    # manual lat/lon
#          df = add_timezone_col(df, datetime_col='timestamp', lat_col='lat', lon_col='lon')     # fully manual


def build_gis_df(df):
    """
    Extract GIS columns from any standardized DataFrame.
    Requires: datetime, timezone, latitude, longitude (from add_timezone_col).
    Optional: altitude — included if detected, skipped if not.
    Keeps all rows as-is, including missing/null values in any column.
    """
    gis_df = get_cols(df, ["datetime", "timezone", "latitude", "longitude", "alt"])

    if "altitude" not in gis_df.columns and any("alt" in col.lower() for col in gis_df.columns):
        gis_df = rename_cols(gis_df, ["alt"], "altitude")

    if "altitude" not in gis_df.columns:
        print("No altitude data available.")

    return gis_df


# ============================================================================================================
# Helpers for Df Builders in parsers/

def get_cols(df, include_keywords, exclude_keywords=None):
    """Find columns with include_keywords and exclude_keywords (case-insensitive)."""
    
    include_pattern = '|'.join(include_keywords) # OR condition, filters for columns with ANY include_keyword 
    cols = df.columns[df.columns.str.contains(include_pattern, case=False, na=False)]
    
    if exclude_keywords:
        exclude_pattern = '|'.join(exclude_keywords) # and then, filters the included columns for columns with ANY exluded_keyword
        cols = cols[~cols.str.contains(exclude_pattern, case=False, na=False)]
    
    return df[cols]   

## Example: get_cols(df, ["pm" "temp"], ["ppm"])

def rename_cols(df, *args, silent=False):
    """Find columns with include_keywords (case-insensitive).
    Sequentially run through the list of (["keywords", "of_old_name"], "new_name") pairs.
    Rename each pair one at a time. Requires ALL keywords to match.
    If no match found for a pair, skip and print a warning unless silent=True."""

    df = df.copy()
    mapping = {}
    used_cols = set()

    for i in range(0, len(args) - 1, 2):
        keywords = args[i]
        new_name = args[i + 1]

        matched = [
            col for col in df.columns
            if all(k.lower() in col.lower() for k in keywords) # k --> keyword, k.lower --> makes keyword lowercase, col.lower --> makes col lowercase ==> ensures case-insensitive
        ]       # all(...) --> ensures ALL keywords must be included 

        matched_unused = [col for col in matched if col not in used_cols]

        if not matched_unused:
            if not silent:
                print(f"Warning: No column found for keywords {keywords} → '{new_name}' — skipping.")
            continue

        col = matched_unused[0]
        mapping[col] = new_name
        used_cols.add(col)

    return df.rename(columns=mapping)

# Example: rename_cols(df, ["pm", "2", "5"], "pm2_5")               # generic skip warnings on
#          rename_cols(df, ["pm", "2", "5"], "pm2_5", silent=True)  # suppress skip warnings


# ============================================================================================================
# Helpers for Df Navigation in notebooks/

def skim_loaded_data(data):
    """
    Displays a summary of all devices and dfs in the loaded pipeline data.

    Parameters
    ----------
    data : dict
        Output of load_pipeline(), structured as:
        { device_type: { device_id: { "data": { table_name: { "df": df, "cols": [...] } } } } }
        Every table — including "gis" and "all" — lives under "data" with no
        special-cased top-level keys.
    """
    for device_type, devices in data.items():
        for device_id, content in devices.items():
            dfs = list(content["data"].keys())
            print(f"{device_type}/{device_id}")
            print(f"  dfs : {dfs}")
            for t in dfs:
                df = content["data"][t]["df"]
                print(f"  {t:10s}: {df.shape}  |  {df['datetime'].min()} → {df['datetime'].max()}")
            print()

def skim(data, device_type=None, device_id=None, df_key=None, col=None):
    # a. no filtering: show everything
    if device_type is None:
        return skim_loaded_data(data)

    # b. filter to one device_type (AKA all device_ids)
    if device_id is None:
        return skim_loaded_data({device_type: data[device_type]})

    # now we have one specific device_id
    content = data[device_type][device_id]

    # c. filter to one specific device_id (and all its dfs)
    if df_key is None:
        return skim_loaded_data({device_type: {device_id: content}})

    # d. filter to one dfs (df_key) -> per-column: name (len, dtype)
    if col is None:
        df = content["data"][df_key]["df"]
        print(f"{device_type}/{device_id}/{df_key}")
        print(f"  df.shape: {df.shape}")  # optional quick sanity line
        for c in df.columns:
            s = df[c]
            # (len, dtype) in a similar style to device summaries
            print(f"  {c:25s}: ({len(s)}, {s.dtype})")
        return df

    # e. filter to one variable-only: one column/Series (same path, minimal metadata)
    s = content["data"][df_key]["df"][col]
    print(f"{device_type}/{device_id}/{df_key}/{col}")
    print(f"  ({len(s)}, {s.dtype})")
    return None

# Examples:   skim(data)                                             # all loaded data
#             skim(data, "Atmotube")                                 # all Atmotube device_ids
#             skim(data, "Atmotube", device_id)                      # one device_id
#             skim(data, "Atmotube", device_id, "pm")                # only pm df
#             skim(data, "Atmotube", device_id, "pm", "pm_2_5_ugm")  # only pm 2.5 column

def get(data, device_type=None, device_id=None, df_key=None, col=None):
    """
    Supports:
        - df_key: str or list/tuple/set
        - col: None, str, or list/tuple/set
        - device_id: str or list/tuple/set
    """
    # a. if no given device_type
    if device_type is None:
        if isinstance(data, dict) and "data" in data:
            return {
                k: v["df"]
                for k, v in data["data"].items()
                if isinstance(v, dict) and "df" in v
            }
        return data

    # b. if no given device_id, return all devices of the given type
    if device_id is None:
        return data[device_type]

    # helper: apply col selection to a DataFrame
    def select_cols(df):
        if col is None:
            return df
        if isinstance(col, (list, tuple, set)):
            return df[list(col)]
        return df[col]

    # NEW: multiple device_ids
    if isinstance(device_id, (list, tuple, set)):
        out = {}
        for did in device_id:
            out[did] = get(data, device_type, did, df_key, col)
        return out

    # c. single device_id
    content = data[device_type][device_id]

    # c1. if df_key is None: flatten all dfs for this device
    if df_key is None:
        return {k: select_cols(v["df"])
                for k, v in content["data"].items()
                if isinstance(v, dict) and "df" in v}

    # c2. df_key is a collection: return {df_key: df(or selected cols)}
    if isinstance(df_key, (list, tuple, set)):
        out = {}
        for k in df_key:
            df = content["data"][k]["df"]
            out[k] = select_cols(df)
        return out

    # c3. df_key is a single key
    df = content["data"][df_key]["df"]
    return select_cols(df)

# Example: atmotube_device_pm2_5 = get(data, "Atmotube", "C7A595F09965_01-May-2026_12-Jun-2026", ["pm"], ["pm2_5_ugm3_atm", "pm10_ugm3_atm"]) # returns the two specified variables from the pm df


def use(dfs, *df_names, how: str = "outer") -> pd.DataFrame:
    """
    Merge a dict of per-category DataFrames into one wide DataFrame, joined
    on "datetime".

    Accepts either a flat {df_key: df} dict or a device content dict
    directly (anything with a "data" key) — normalizes via get() internally,
    so you don't need to flatten first.

    By default merges every table. Pass specific table names as positional
    args to merge only those instead.

    Args:
        dfs: flat {df_key: df} dict, or a device dict (get() flattens it).
        *df_names: optional table names to merge (e.g. "pm", "weather").
                If omitted, every table is merged.
        how: join type passed to pd.merge (default "outer" — preserves
            every timestamp present in ANY table, not just whichever
            table happens to be first).
    """
    dfs = get(dfs)  # pass-through if already flat; flattens if it's a device dict

    if df_names:
        invalid = [n for n in df_names if n not in dfs]
        if invalid:
            print(f"df(s) not found: {invalid}. Available: {list(dfs.keys())}")
            return None
        dfs = [dfs[n] for n in df_names]
    else:
        dfs = list(dfs.values())

    if not dfs:
        return pd.DataFrame()

    return reduce(
        lambda left, right: pd.merge(left, right, on="datetime", how=how),
        dfs
    )

# use(device)                              # merge everything; device dict normalized via get()
# use(get(data, "Atmotube", device_id))     # equivalent, pre-flattened
# use(device, "pm", "weather")              # just pm + weather, joined on datetime