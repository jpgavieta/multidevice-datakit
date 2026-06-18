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
    skip    = {"all", "gis"}
    dfs     = {k: v["df"] for k, v in device["data"].items()}
    # dfs["gis"] = device["raw_gis"]                                  # to see missing lon/lat shit
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

def profile_df(device, table, title=None):
    from ydata_profiling import ProfileReport
    df = device["all"] if table == "all" else device["data"][table]["df"]
    return ProfileReport(df, title=title, minimal=False)

# Example: profile_df(d1, "pm", title="PM - Device 1").to_notebook_iframe()
# Example: profile_df(d1, "all", title="All - Device 1").to_notebook_iframe()