import pandas as pd


# def _get_numeric_cols(df):
#     """Return all numeric columns except datetime, date, time."""
#     skip = {"datetime", "date", "time"}
#     return [
#         col for col in df.columns
#         if col not in skip and pd.api.types.is_numeric_dtype(df[col])
#     ]


def _resolve_targets(dfs, df_names, skip):
    """Resolve which dfs to operate on."""
    if df_names:
        invalid = [n for n in df_names if n not in dfs]
        if invalid:
            print(f"df(s) not found: {invalid}. Available: {[k for k in dfs if k not in skip]}")
            return None
        return {n: dfs[n] for n in df_names}
    return {k: v for k, v in dfs.items() if k not in skip}


def report_loss(device, *df_names):
    skip    = {"all", "gis,", "raw_gis"}
    dfs     = {k: v["df"] for k, v in device["data"].items()}
    dfs["gis"] = device["raw_gis"]                                  # to see missing lon/lat shit
    targets = _resolve_targets(dfs, df_names, skip)
    if targets is None:
        return

    print(f"{'df':<10} {'column':<25} {'rows':>8} {'missing':>8} {'coverage':>10}")
    print("─" * 68)

    for name, df in targets.items():
        total_rows = df.shape[0]          # ← per-df row count
        for col in df.columns:
            if col in {"datetime", "date", "time"}:
                continue
            missing  = df[col].isna().sum()
            coverage = (1 - missing / total_rows) * 100
            bar      = "█" * int(coverage / 10) + "░" * (10 - int(coverage / 10))
            print(f"{name:<10} {col:<25} {total_rows:>8} {missing:>8} {coverage:>8.1f}%  {bar}")
        print()

# report_loss(d1)              # all tables
# report_loss(d1, "pm")        # just pm
# report_loss(d1, "pm", "gas") # pm and gas

# def profile_df(df, title=None):
#     """Generate an interactive profile report for a dataframe.

#     Parameters
#     ----------
#     df    : pd.DataFrame
#     title : str, optional
#     """
#     from ydata_profiling import ProfileReport
#     return ProfileReport(df, title=title, minimal=False)

# # Example: profile_df(d1["data"]["pm"]["df"], title="PM - Device 1").to_notebook_iframe()
# # Example: profile_df(d1["all"], title="All - Device 1").to_notebook_iframe()

def profile_df(device, table=None, title=None, minimal=False):
    """
    Profile a dataframe from a device using ydata-profiling.
    
    Parameters:
    -----------
    device : dict
        Device data dictionary containing "all" and "data" keys
    table : str, optional
        Table name to profile ("pm", "gas", "weather", etc.)
        If None, profiles the merged "all" dataframe.
    title : str, optional
        Custom title for the ProfileReport
    minimal : bool
        If True, generates a minimal report (faster). Default False.
    
    Returns:
    --------
    ProfileReport object
    
    Raises:
    -------
    KeyError: if table name doesn't exist in device
    """
    from ydata_profiling import ProfileReport
    
    # Validate device structure
    if "all" not in device or "data" not in device:
        raise KeyError("Device must contain 'all' and 'data' keys")
    
    # Select dataframe
    if table is None:
        df = device["all"]
        if title is None:
            title = "Merged Data (All Tables)"
    else:
        # Validate table exists
        if table not in device["data"]:
            available = list(device["data"].keys())
            raise KeyError(f"Table '{table}' not found. Available tables: {available}")
        
        df = device["data"][table]["df"]
        if title is None:
            title = f"Device Data - {table.upper()}"
    
    # Validate dataframe
    if df is None or df.empty:
        raise ValueError(f"Dataframe for '{table or 'all'}' is empty or None")
    
    print(f"Profiling {title}... Shape: {df.shape}")
    return ProfileReport(df, title=title, minimal=minimal)

# Example: report_pm = profile_df(d1, table="pm") # Profile a specific table
# Example: report_gas = profile_df(d1, table="gas", minimal=True)  # Faster report

# Example: report_all = profile_df(d1)  # Uses device["all"] # Profile the merged dataframe

# Example: report = profile_df(d1, table="weather", title="Device 1 - Weather Data") # With custom title

# for table_name in ["pm", "gas", "weather", "phone", "sat", "txt"]: # Profile all tables for a device
#   report = profile_df(d1, table=table_name)#     report = profile_df(d1, table=table_name)
#   etc...
