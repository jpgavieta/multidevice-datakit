import re

import json
import pandas as pd 

from functools import reduce
from typeguard import value
from tzfpy import get_tz

from typing import Any, Dict, Optional, Literal, cast

from datetime import datetime

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

    candidates: Dict[str, float] = {}

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

    best_col = max(candidates, key=candidates.__getitem__)

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

    lat_candidates: Dict[str, float] = {}
    lon_candidates: Dict[str, float] = {}

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

    lat_col = max(lat_candidates, key=lambda col: lat_candidates[col]) if lat_candidates else None
    lon_col = max(lon_candidates, key=lambda col: lon_candidates[col]) if lon_candidates else None

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


def build_gis_df(df: pd.DataFrame) -> Optional[pd.DataFrame]:
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

# Example: get_cols(df, ["pm" "temp"], ["ppm"])

def rename_cols(df, *args, silent=False):
    """
    Find columns with include_keywords (case-insensitive).
    Sequentially run through the list of (["keywords", "of_old_name"], "new_name") pairs.
    Rename each pair one at a time. Requires ALL keywords to match.
    If no match found for a pair, skip and print a warning unless silent=True.
    """

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

    # one or more device_types
    if isinstance(device_type, (list, tuple, set)):
        for dt in device_type:
            if dt not in data:
                print(f"⚠️ {dt} is not available")
                continue
            skim(data, dt, device_id, df_key, col)
        return None

    if device_type not in data:
        print(f"⚠️ {device_type} is not available")
        return None

    # b. filter to one device_type (all its device_ids)
    if device_id is None:
        return skim_loaded_data({device_type: data[device_type]})

    # one or more device_ids
    if isinstance(device_id, (list, tuple, set)):
        for did in device_id:
            if did not in data[device_type]:
                print(f"⚠️ {did} is not available")
                continue
            skim(data, device_type, did, df_key, col)
        return None

    if device_id not in data[device_type]:
        print(f"⚠️ {device_id} is not available")
        return None

    # now we have one specific device_id
    content = data[device_type][device_id]

    # c. filter to one specific device_id (all its dfs)
    if df_key is None:
        return skim_loaded_data({device_type: {device_id: content}})

    # one or more df_keys
    if isinstance(df_key, (list, tuple, set)):
        for dk in df_key:
            if dk not in content["data"]:
                print(f"⚠️ {dk} is not available")
                continue
            skim(data, device_type, device_id, dk, col)
        return None

    if df_key not in content["data"]:
        print(f"⚠️ {df_key} is not available")
        return None

    df = content["data"][df_key]["df"]

    # d. filter to one df (df_key) -> per-column: name (len, dtype)
    if col is None:
        print(f"{device_type}/{device_id}/{df_key}")
        print(f"  df.shape: {df.shape}")
        if "datetime" in df.columns:
            print(f"  range   : {df['datetime'].min()} → {df['datetime'].max()}")
        for c in df.columns:
            s = df[c]
            print(f"  {c:25s}: ({len(s)}, {s.dtype})")
        return None

    # one or more cols
    if isinstance(col, (list, tuple, set)):
        for c in col:
            if c not in df.columns:
                print(f"⚠️ {c} is not available")
                continue
            skim(data, device_type, device_id, df_key, c)
        return None

    if col not in df.columns:
        print(f"⚠️ {col} is not available")
        return None

    # e. filter to one variable-only: one column/Series
    s = df[col]
    print(f"{device_type}/{device_id}/{df_key}/{col}")
    print(f"  ({len(s)}, {s.dtype})")
    if "datetime" in df.columns and col != "datetime":
        valid_dt = df.loc[s.notna(), "datetime"]
        if not valid_dt.empty:
            print(f"  range   : {valid_dt.min()} → {valid_dt.max()}  (where '{col}' is present)")
        else:
            print(f"  range   : no non-null values for '{col}'")
    return None

# Examples:
#   skim(data)                                                                   # all loaded data
#   skim(data, "Atmotube")                                                       # all Atmotube device_ids
#   skim(data, ["Atmotube", "Ponyopi"])                                          # all device_ids, both device types
#   skim(data, "Atmotube", device_id)                                            # one device_id, all its dfs
#   skim(data, "Atmotube", [device_a, device_b])                                 # two device_ids, all dfs each
#   skim(data, "Atmotube", device_id, "pm")                                      # one df
#   skim(data, "Atmotube", device_id, ["pm", "weather"])                         # two dfs, one device  
#   skim(data, "Atmotube", [device_a, device_b], "pm")                           # same df, two devices
#   skim(data, "Atmotube", device_id, "pm", "pm2_5_ugm3_atm")                    # one column
#   skim(data, "Atmotube", device_id, "pm", ["pm2_5_ugm3_atm", "pm10_ugm3_atm"]) # two columns


def unwrap(content: Any) -> Dict[str, pd.DataFrame]:
    """
    Unwraps ONE device's content (a nested dict) into a flat dict of {df_key: df} — the
    raw material merge() expects.

    Accepts:
    -   a device content dict (has a "data" key): unwraps content["data"],
        pulling just the "df" out of each {"df": df} entry.
    -   an already-flat {df_key: df} dict: returned unchanged, so calling
        unwrap() on something already extracted is always safe.
    """
    if isinstance(content, dict) and "data" in content:
        return {
            k: v["df"]
            for k, v in content["data"].items()
            if isinstance(v, dict) and "df" in v
        }
    return content

# Example:
#   unwrap(get(data, "device_type", "device_id"))      
#   OR
#   device = get(data, "device_type", "device_id")      
#   unwrap(device)                                    # equivalent — get() already returns this same shape


def merge(
    *dfs_dicts,
    df_names=None,
    how: Literal['left', 'right', 'outer', 'inner', 'cross', 'left_anti', 'right_anti'] = "outer",
    **named_dicts
):
    """
    Merge function for the unwrap() output (dict of {table_name: df}) into one
    wide DataFrame joined on "datetime".
    Supports:
    -   One positional dict (unnamed device): no column suffixing
    -   Multiple named devices via keyword args (device_name=dict): suffix all
        non-"datetime" columns with _<device_name>
    -   df_names: str or list/tuple/set to select which tables to merge
    -   how: join type for pd.merge (default "outer")

    Raises:
        ValueError: if both positional and named dicts are given, if
            multiple unnamed positional dicts are given, or if a requested
            df_name isn't found in a device's tables.
    """
    if dfs_dicts and named_dicts:
        raise ValueError("Pass either one positional dict, or named devices via keyword args — not both.")
    if dfs_dicts:
        if len(dfs_dicts) != 1:
            raise ValueError(
                "Multiple dicts given without names — use keyword args instead "
                "(e.g. merge(device_a=dict_a, device_b=dict_b)) so each has a "
                "name to suffix columns with."
            )
        devices = {None: dfs_dicts[0]}
    else:
        devices = named_dicts

    suffix_needed = len(devices) > 1
    all_tables = []
    for device_name, dfs in devices.items():
        if df_names:
            invalid = [n for n in df_names if n not in dfs]
            if invalid:
                label = f"'{device_name}'" if device_name else "the dict"
                raise ValueError(
                    f"df(s) not found in {label}: {invalid}. Available: {list(dfs.keys())}"
                )
            tables = [dfs[n] for n in df_names]
        else:
            tables = list(dfs.values())
        if suffix_needed:
            tables = [
                t.rename(columns={c: f"{c}_{device_name}" for c in t.columns if c != "datetime"})
                for t in tables
            ]
        all_tables.extend(tables)

    if not all_tables:
        return pd.DataFrame()

    return reduce(
        lambda left, right: pd.merge(left, right, on="datetime", how=how),
        all_tables
    )

# Example:
#   merge(unwrap(device))                                                          # one device, all tables, no suffix
#   merge(unwrap(device), df_names=["pm"])                                         # one device, just pm
#   merge(device_a=unwrap(content_a), device_b=unwrap(content_b))                  # two devices, all tables, suffixed
#   merge(device_a=unwrap(content_a), device_b=unwrap(content_b), df_names=["pm"]) # two devices, just pm, suffixed


def get(data, device_type=None, device_id=None, df_key=None, col=None):
    """
    The single navigation function for the nested pipeline structure.
    Always returns a dict or a Series — never a bare DataFrame at the top
    level.

    Unwrapping a table's {"df": df} entry into an actual DataFrame
    happens exclusively inside unwrap() — get() never reaches into ["df"]
    itself.

    Supports:
        - device_type: str or list/tuple/set
        - device_id: str or list/tuple/set
        - df_key: str or list/tuple/set
        - col: None, str, or list/tuple/set

    Raises:
        KeyError: if a SINGLE device_type/device_id/df_key/col is given
            and it isn't found.
    Note:
        When given as part of a list/tuple/set, a missing item is instead
        skipped with a warning, so one bad ID doesn't abort a batch lookup.
    """
    # a. if no given device_type
    if device_type is None:
        return unwrap(data)

    # one or more device_types
    if isinstance(device_type, (list, tuple, set)):
        out = {}
        for dt in device_type:
            if dt not in data:
                print(f"⚠️ device_type '{dt}' is not available")
                continue
            out[dt] = get(data, dt, device_id, df_key, col)
        return out

    if device_type not in data:
        raise KeyError(f"device_type '{device_type}' is not available")

    # b. if no given device_id, return all devices of the given type
    if device_id is None:
        return data[device_type]

    # helper: select column(s) from a DataFrame.
    #   col is None  -> df unchanged (still a DataFrame, but only ever as
    #                   a dict VALUE — never returned bare at top level)
    #   col is a str -> a Series
    #   col is a list/tuple/set -> dict {col_name: Series}, never a
    #                   sub-DataFrame
    def select_cols(df, table_name, did, dtypename):
        if col is None:
            return df

        if isinstance(col, (list, tuple, set)):
            # Always keep datetime, even if the caller didn't ask for it —
            # merge() needs it to join tables together.
            cols_to_use = list(col)
            if "datetime" in df.columns and "datetime" not in cols_to_use:
                cols_to_use = ["datetime"] + cols_to_use

            missing = [c for c in cols_to_use if c not in df.columns]
            for c in missing:
                print(
                    f"⚠️ col '{c}' is not available in df '{table_name}' "
                    f"(device_type '{dtypename}', device_id '{did}')"
                )

            valid_cols = [c for c in cols_to_use if c in df.columns]
            return df[valid_cols]  # DataFrame, not a dict of Series

        if col not in df.columns:
            raise KeyError(
                f"col '{col}' is not available in df '{table_name}' "
                f"(device_type '{dtypename}', device_id '{did}')"
            )

        return df[col]  # still a Series for a single column name — see note below

    # one or more device_ids
    if isinstance(device_id, (list, tuple, set)):
        out = {}
        for did in device_id:
            if did not in data[device_type]:
                print(
                    f"⚠️ device_id '{did}' is not available in device_type '{device_type}'"
                )
                continue
            out[did] = get(data, device_type, did, df_key, col)
        return out

    if device_id not in data[device_type]:
        raise KeyError(
            f"device_id '{device_id}' is not available in device_type '{device_type}'"
        )

    # c. single device_id — unwrap once via unwrap(), use it everywhere below
    content = data[device_type][device_id]
    dfs = unwrap(content)  # {table_name: df, ...} — the ONLY unwrap point

    # c1. if df_key is None: every table for this device
    if df_key is None:
        return {
            k: select_cols(df, k, device_id, device_type) for k, df in dfs.items()
        }

    # c2. df_key is a collection: just those tables, always as a dict
    if isinstance(df_key, (list, tuple, set)):
        out = {}
        for k in df_key:
            if k not in dfs:
                print(
                    f"⚠️ df '{k}' is not available in device_id '{device_id}' "
                    f"(device_type '{device_type}')"
                )
                continue
            out[k] = select_cols(dfs[k], k, device_id, device_type)
        return out

    if df_key not in dfs:
        raise KeyError(
            f"df '{df_key}' is not available in device_id '{device_id}' "
            f"(device_type '{device_type}')"
        )

    # c3. df_key is a single key — still wrapped in a dict, since a bare
    # DataFrame is never the top-level return. col=None -> {df_key: df};
    # col=str -> a Series (the one non-dict result, and that's allowed);
    # col=list -> dict of Series, via select_cols.
    result = select_cols(dfs[df_key], df_key, device_id, device_type)
    if col is None:
        return {df_key: result}
    return result

# Examples:
#   get(data)                                                                   # entire loaded dataset, unchanged
#   get(data, "Atmotube")                                                       # all Atmotube device_ids, NOT flattened
#   get(data, "Atmotube", device_id)                                            # one device, flattened to {df_key: df}
#   get(data, "Atmotube", [device_a, device_b])                                 # two devices, each flattened to {df_key: df}
#   get(data, "Atmotube", device_id, "pm")                                      # one df
#   get(data, "Atmotube", device_id, ["pm", "weather"])                         # two dfs, one device
#   get(data, "Atmotube", [device_a, device_b], "pm")                           # same df, two devices, NOT merged
#   get(data, "Atmotube", device_id, "pm", "pm2_5_ugm3_atm")                    # one column
#   get(data, "Atmotube", device_id, "pm", ["pm2_5_ugm3_atm", "pm10_ugm3_atm"]) # two columns


from IPython.display import HTML, display
from IPython.utils.capture import capture_output
import html as html_lib
from typing import TypeVar, Callable

T = TypeVar('T')

def scroll_output(func: Callable[..., T], *args, height: str = "400px", plot_height: str = "800px", center: bool = True, **kwargs) -> T:
    """
    Execute a function, capture output, and render inside a scrollable box.
    Set center=True to horizontally center all content.
    Automatically increases height if plots are detected.
    """
    with capture_output() as captured:
        result = func(*args, **kwargs)

    parts = []
    has_plot = False

    if captured.stdout:
        parts.append(f"<pre>{html_lib.escape(captured.stdout)}</pre>")

    for output in captured.outputs:
        data = output.data
        if "text/html" in data:
            parts.append(data["text/html"])
            # Detect interactive plots (Plotly, Altair, etc. use HTML)
            if any(tag in data["text/html"].lower() for tag in ["plotly", "vega", "bokeh", "script"]):
                has_plot = True
        elif "image/png" in data:
            b64 = data["image/png"]
            parts.append(f'<img src="data:image/png;base64,{b64}" style="max-width:100%;">')
            has_plot = True  # Matplotlib, seaborn, etc.
        elif "text/plain" in data:
            parts.append(f"<pre>{html_lib.escape(data['text/plain'])}</pre>")

    inner_html = "".join(parts)

    # Use appropriate height based on plot detection
    final_height = plot_height if has_plot else height

    # Base styles
    base_style = (
        f"max-height: {final_height}; overflow-y: auto; border: 1px solid #ccc; "
        f"padding: 8px; background: #f5f5f5; color: #000; "
        f"font-family: monospace; white-space: normal;"
    )
    
    # Add centering styles if requested
    if center:
        base_style += " display: flex; flex-direction: column; align-items: center; text-align: center;"

    display(HTML(f'<div style="{base_style}">{inner_html}</div>'))

    return result

# ============================================================================================================
# Helpers for multifiles per device_id in notebooks/

## WARNING: File extraction helpers (legacy method)
## TODO: Remove when migrated to API-based extraction

_DEVICE_KEY_PATTERN = re.compile(r"^(?P<device_id>[A-Za-z0-9]+)_(?P<dates>.+)$")
_DATE_FORMAT = "%d-%b-%Y"


def _parse_device_key(device_key: str):
    """
    Parses a device_id key like 'C7A595F09965_01-May-2026_12-Jun-2026' or
    'DB7A737B8CA0_30-Jun-2026' into (true_id, start_date, end_date).
    If only one date is present, start_date == end_date.
    Returns (None, None, None) if the key doesn't match the expected shape.
    """
    match = _DEVICE_KEY_PATTERN.match(device_key)
    if not match:
        return None, None, None

    true_id = match.group("device_id")
    date_parts = match.group("dates").split("_")

    dates = []
    for part in date_parts:
        try:
            dates.append(datetime.strptime(part.strip(), _DATE_FORMAT))
        except ValueError:
            continue  # skip anything that doesn't parse (e.g. malformed dates)

    if not dates:
        return true_id, None, None
    if len(dates) == 1:
        return true_id, dates[0], dates[0]
    return true_id, dates[0], dates[-1]


def list_device_ids(data: dict, device_type: str) -> list[str]:
    """Returns the sorted, de-duplicated list of true device IDs (serials) for a device_type."""
    ids = set()
    for device_key in data.get(device_type, {}):
        true_id, _, _ = _parse_device_key(device_key)
        if true_id:
            ids.add(true_id)
    return sorted(ids)


def find_files_for_id(data: dict, device_type: str, true_id: str) -> list[str]:
    """Returns all device_id keys (filenames) belonging to one physical device, oldest to newest."""
    matches = []
    for device_key in data.get(device_type, {}):
        parsed_id, start, _ = _parse_device_key(device_key)
        if parsed_id == true_id:
            matches.append((device_key, start))
    matches.sort(key=lambda pair: (pair[1] is None, pair[1]))
    return [key for key, _ in matches]


def latest_file_for_id(data: dict, device_type: str, true_id: str) -> str | None:
    """Returns the device_id key (filename) with the most recent end_date for a given true device ID."""
    matches = []
    for device_key in data.get(device_type, {}):
        parsed_id, _, end = _parse_device_key(device_key)
        if parsed_id == true_id and end is not None:
            matches.append((device_key, end))
    if not matches:
        return None
    matches.sort(key=lambda pair: pair[1])
    return matches[-1][0]

def merge_device_files(data: dict, device_type: str, true_id: str) -> dict[str, pd.DataFrame]:
    """
    Merges all file-chunks belonging to one physical device (true_id) into
    a single {table_name: DataFrame} dict, ordered chronologically.

    Overlapping rows that are IDENTICAL across files are deduplicated,
    keeping the version from the OLDEST file. Overlapping rows with
    DIFFERING values are both kept (resulting in duplicate datetimes) —
    this surfaces the conflict rather than silently picking a winner.
    """
    keys = find_files_for_id(data, device_type, true_id)  # oldest -> newest
    if not keys:
        return {}

    table_frames: dict[str, list[pd.DataFrame]] = {}
    for key in keys:
        content = get(data, device_type, key)  # {table_name: DataFrame}, already unwrapped
        for table_name, df in content.items():
            table_frames.setdefault(table_name, []).append(df)

    merged_tables = {}
    for table_name, dfs in table_frames.items():
        combined = pd.concat(dfs, ignore_index=True)

        if "datetime" in combined.columns:
            # stable sort preserves original (chronological file) order for
            # rows that share the same datetime — required for keep="first"
            # to correctly favor the OLDEST file's version
            combined = combined.sort_values("datetime", kind="stable")

        before = len(combined)
        combined = combined.drop_duplicates(keep="first").reset_index(drop=True)
        dropped = before - len(combined)

        # flag any datetimes that still repeat after dedup — these are
        # genuine conflicts (same timestamp, different values)
        if "datetime" in combined.columns:
            conflict_count = combined["datetime"].duplicated().sum()
            if conflict_count > 0:
                print(
                    f"⚠️ {true_id} / {table_name}: {conflict_count} datetime(s) "
                    f"still duplicated after merge — same timestamp, differing values"
                )

        merged_tables[table_name] = combined

    return merged_tables


def consolidate_device_ids(data: dict, device_type: str) -> dict[str, dict[str, pd.DataFrame]]:
    """
    Merges all file-chunks for every physical device under a device_type
    into one entry per true device ID.

    Returns
    -------
    dict
        { true_device_id: { table_name: merged_DataFrame } }
    """
    ids = list_device_ids(data, device_type)
    return {true_id: merge_device_files(data, device_type, true_id) for true_id in ids}