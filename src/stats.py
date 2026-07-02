# src/stats.py
import pandas as pd
from typing import Mapping

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import matplotlib.patches as mpatches

import math


# ============================================================================================================
# Helpers

def _get_numeric_cols(df: pd.DataFrame) -> list[str]:
    skip = {"datetime", "date", "time"}
    cols = []
    for col in df.columns:
        if col in skip:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            if df[col].dtype == "bool":
                continue
            # also exclude pandas nullable boolean
            if pd.api.types.is_bool_dtype(df[col].dtype):
                continue
            cols.append(col)
    return cols


def _resolve_targets(dfs: Mapping[str, pd.DataFrame], df_names: tuple[str, ...], skip: set[str]) -> dict[str, pd.DataFrame] | None:
    if df_names:
        invalid = [n for n in df_names if n not in dfs]
        if invalid:
            print(f"df(s) not found: {invalid}. Available: {[k for k in dfs if k not in skip]}")
            return None
        return {n: dfs[n] for n in df_names}
    return {k: v for k, v in dfs.items() if k not in skip}

def filter_date_range(
    device: dict[str, pd.DataFrame],
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Returns a new {table_name: DataFrame} dict, each table filtered to rows
    where 'datetime' falls within [start, end] (inclusive). Tables without
    a 'datetime' column, or with start/end left as None, pass through
    unfiltered on that bound.
    """
    start_ts = pd.Timestamp(start, tz="UTC") if start is not None else None
    end_ts = pd.Timestamp(end, tz="UTC") if end is not None else None

    filtered = {}
    for table_name, df in device.items():
        if "datetime" not in df.columns:
            filtered[table_name] = df
            continue

        mask = pd.Series(True, index=df.index)
        if start_ts is not None:
            mask &= df["datetime"] >= start_ts
        if end_ts is not None:
            mask &= df["datetime"] <= end_ts

        filtered[table_name] = df[mask].reset_index(drop=True)

    return filtered


# ============================================================================================================

# def report_loss(dfs, *df_names): # good night sweet prince, you were my favourite
#     """
#     Reports data quality metrics: row counts, missing values, and coverage %.
#     Includes a visual bar for coverage.
#     """
#     if not dfs:
#         print("⚠️ No data to report on.")
#         return
#     if not isinstance(dfs, dict):
#         raise TypeError(f"dfs must be a dict of DataFrames; got {type(dfs)}")

#     skip = {"all"}
#     targets = _resolve_targets(dfs, df_names, skip)
#     if targets is None:
#         return

#     print(f"{'df':<10} {'column':<25} {'rows':>8} {'missing':>8} {'coverage':>10}")
#     print("─" * 68)

#     for name, df in targets.items():
#         if df is None:
#             continue
#         total_rows = df.shape[0]
#         for col in df.columns:
#             if col in {"datetime", "date", "time"}:
#                 continue

#             missing = df[col].isna().sum()
#             coverage = (1 - missing / total_rows) * 100 if total_rows > 0 else 0.0

#             bar_len = int(coverage / 10)
#             bar = "█" * bar_len + "░" * (10 - bar_len)

#             print(f"{name:<10} {col:<25} {total_rows:>8} {missing:>8} {coverage:>8.1f}%  {bar}")
#         print()


def report_loss(dfs, *df_names):
    """
    Returns a DataFrame of data quality metrics: row counts, missing values, and coverage %.
    """
    if not dfs:
        return pd.DataFrame()
    if not isinstance(dfs, dict):
        raise TypeError(f"dfs must be a dict of DataFrames; got {type(dfs)}")

    targets = _resolve_targets(dfs, df_names, skip={"all"})
    if targets is None:
        return pd.DataFrame()

    rows = []
    for name, df in targets.items():
        if df is None:
            continue
        total_rows = df.shape[0]
        for col in df.columns:
            if col in {"datetime", "date", "time"}:
                continue
            missing = int(df[col].isna().sum())
            coverage = (1 - missing / total_rows) * 100 if total_rows > 0 else 0.0
            rows.append({
                "df":       name,
                "column":   col,
                "rows":     total_rows,
                "missing (n)":  missing,
                "coverage (%)": coverage,
            })

    return pd.DataFrame(rows)


def plot_loss(df: pd.DataFrame, ncols: int = 3):
    """
    Plots coverage % per column, grouped by (df, base_column) into subplots.
    Columns with an underscore suffix (e.g. temp_c_d1) are treated as
    base_column + device_label and grouped into the same subplot.
    """
    if df.empty:
        print("⚠️ No data to plot.")
        return None

    df = df.copy()

    if "_" in "".join(df["column"]):
        split = df["column"].str.rsplit("_", n=1, expand=True)
        df["base_column"]  = split[0]
        df["device_label"] = split[1].fillna("")
    else:
        df["base_column"]  = df["column"]
        df["device_label"] = ""

    groups = list(df.groupby(["df", "base_column"], sort=False))
    n      = len(groups)
    ncols  = min(ncols, n)
    nrows  = math.ceil(n / ncols)

    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 4, nrows * 3.5), squeeze=False)
    axes_flat = axes.flatten()

    for ax, ((table_name, col_name), grp) in zip(axes_flat, groups):
        grp  = grp.reset_index(drop=True)
        xs   = range(len(grp))
        bars = ax.bar(xs, grp["coverage"], color="#4C72B0", alpha=0.75, width=0.5)

        # Colour bars below 80% amber, below 50% red
        for bar, (_, row) in zip(bars, grp.iterrows()):
            if row["coverage"] < 50:
                bar.set_color("#D94F3D")
            elif row["coverage"] < 80:
                bar.set_color("#E5A124")

        ax.set_ylim(0, 105)
        ax.axhline(100, color="#aaaaaa", linewidth=0.8, linestyle="--")
        ax.set_xticks(xs)
        ax.set_xticklabels(grp["device_label"], fontsize=7, rotation=30, ha="right")
        ax.set_title(f"{table_name}\n{col_name}", fontsize=9)
        # ax.set_ylabel("Coverage %", fontsize=8)
        ax.tick_params(labelsize=7)

    for j in range(n, len(axes_flat)):
        axes_flat[j].axis("off")

    legend = [
        mpatches.Patch(color="#4C72B0", alpha=0.75, label="≥ 80%"),
        mpatches.Patch(color="#E5A124",              label="50–80%"),
        mpatches.Patch(color="#D94F3D",              label="< 50%"),
    ]
    fig.legend(handles=legend, fontsize=9, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.02))
    # fig.suptitle("Data Coverage by Column", fontsize=13, y=1.06)
    plt.tight_layout()
    plt.close(fig)
    return fig


# ============================================================================================================


def report_global_range(dfs, *df_names):
    """
    Returns a DataFrame of global summary stats (min, Q25, median, mean, Q75, max)
    for each column. Does not plot — use plot_global_range() separately.
    """
    if not dfs:
        return pd.DataFrame()
    if not isinstance(dfs, dict):
        raise TypeError(f"dfs must be a dict of DataFrames; got {type(dfs)}")

    targets = _resolve_targets(dfs, df_names, skip={"all"})
    if targets is None:
        return pd.DataFrame()

    rows = []
    for name, df in targets.items():
        if df is None or "datetime" not in df.columns:
            continue

        df2 = df.dropna(subset=["datetime"]).sort_values("datetime").set_index("datetime")
        for col in _get_numeric_cols(df2):
            s = df2[col].astype(float).dropna()
            if s.empty:
                continue
            rows.append({
                "df":     name,
                "column": col,
                "n":      int(s.shape[0]),
                "min":    float(s.min()),
                "q25":    float(s.quantile(0.25)),
                "median": float(s.median()),
                "mean":   float(s.mean()),
                "q75":    float(s.quantile(0.75)),
                "max":    float(s.max()),
            })

    return pd.DataFrame(rows)

def plot_global_range(df: pd.DataFrame, ncols: int = 3):
    """
    Plots a quartile range chart from a report_global_range() result.
    If a column name contains an underscore (e.g. "temp_c_d1", produced by
    merge()'s device suffixing), everything before the LAST underscore is
    treated as the base column, and everything after it as a device label
    — grouping same-named columns from different devices into one subplot,
    with a bar per device. Columns with no underscore get their own subplot.
    Subplots are grouped by table (df), so each table's columns appear
    together in the grid.
    Returns the Figure, or None if there's no data to plot.
    """
    if df.empty:
        print("⚠️ No data to plot.")
        return None

    df = df.copy()

    if "_" in "".join(df["column"]):
        split = df["column"].str.rsplit("_", n=1, expand=True)
        df["base_column"] = split[0]
        df["device_label"] = split[1].fillna("")
    else:
        df["base_column"] = df["column"]
        df["device_label"] = ""

    
    groups = list(df.groupby(["df", "base_column"], sort=False))
    n = len(groups)
    ncols = min(ncols, n)
    nrows = math.ceil(n / ncols)

    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 4, nrows * 3.5), squeeze=False)
    axes_flat = axes.flatten()

    for ax, ((table_name, col_name), grp) in zip(axes_flat, groups):
        grp = grp.reset_index(drop=True)

        for i, (_, row) in enumerate(grp.iterrows()):
            x = i

            ax.plot([x, x], [row["min"], row["max"]], color="#aaaaaa", linewidth=1.5, zorder=1)
            ax.bar(x, row["q75"] - row["q25"], bottom=row["q25"],
                color="#4C72B0", alpha=0.6, width=0.5, zorder=2)
            ax.plot([x - 0.22, x + 0.22], [row["median"], row["median"]],
                    color="#0C254D", linewidth=1.5, zorder=3)
            ax.plot(x, row["mean"], marker="D", color="#E56B24", markersize=6, zorder=4)

        ax.set_xticks(range(len(grp)))
        ax.set_xticklabels(grp["device_label"], fontsize=7, rotation=30, ha="right")
        ax.set_title(f"{table_name}\n{col_name}", fontsize=9)
        # ax.set_ylabel("Value", fontsize=8)
        ax.tick_params(labelsize=7)

    for j in range(n, len(axes_flat)):
        axes_flat[j].axis("off")

    legend = [
        mpatches.Patch(color="#4C72B0", alpha=0.6, label="IQR (Q25–Q75)"),
        Line2D([0], [0], color="#0C254D", linewidth=1.5, label="Median"),
        Line2D([0], [0], marker="D", color="#E56B24", linestyle="None", label="Mean"),
        Line2D([0], [0], color="#aaaaaa", linewidth=1.5, label="Min–Max"),
    ]
    fig.legend(handles=legend, fontsize=9, loc="upper center", ncol=4, bbox_to_anchor=(0.5, 1.02))
    # fig.suptitle("Global Range Summary", fontsize=13, y=1.06)
    plt.tight_layout()
    plt.close(fig)
    return fig


# ============================================================================================================


def report_rolling_range(dfs, window="10D", center="median", *df_names):
    """
    Returns a time-indexed DataFrame of rolling min/max/mean/median per column.
    Does not plot — use plot_rolling_range() separately.
    """
    if not dfs:
        return pd.DataFrame()
    if not isinstance(dfs, dict):
        raise TypeError(f"dfs must be a dict of DataFrames; got {type(dfs)}")

    targets = _resolve_targets(dfs, df_names, skip={"all"})
    if targets is None:
        return pd.DataFrame()

    center_mode = center.lower() if isinstance(center, str) else "median"
    if center_mode not in {"mean", "median"}:
        center_mode = "median"

    frames = []
    for name, df in targets.items():
        if df is None or "datetime" not in df.columns:
            continue

        df2 = df.dropna(subset=["datetime"]).sort_values("datetime").set_index("datetime")
        for col in _get_numeric_cols(df2):
            s = df2[col].astype(float).dropna().sort_index()
            if s.empty:
                continue

            r = s.rolling(window=window, min_periods=1)
            frames.append(
                pd.DataFrame({
                    "df":          name,
                    "column":      col,
                    "roll_min":    r.min(),
                    "roll_max":    r.max(),
                    "roll_mean":   r.mean(),
                    "roll_median": r.median(),
                })
            )

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames).sort_index()

def plot_rolling_range(df: pd.DataFrame, ncols: int = 2):
    """
    Plots rolling range line charts, grouped by (df, base_column) into subplots
    — one line/band per device within each subplot (matching plot_global_range
    and plot_loss grouping logic).
    """
    if df.empty:
        print("⚠️ No data to plot.")
        return None

    df = df.copy()

    if "_" in "".join(df["column"]):
        split = df["column"].str.rsplit("_", n=1, expand=True)
        df["base_column"] = split[0]
        df["device_label"] = split[1].fillna("")
    else:
        df["base_column"] = df["column"]
        df["device_label"] = ""

    groups = list(df.groupby(["df", "base_column"], sort=False))
    n = len(groups)
    ncols = min(ncols, n)
    nrows = math.ceil(n / ncols)

    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 6, nrows * 3.5), squeeze=False)
    axes_flat = axes.flatten()

    # Assign each device a consistent color across all subplots
    all_devices = list(dict.fromkeys(df["device_label"]))  # preserves first-seen order
    palette = plt.cm.tab10.colors
    device_colors = {dev: palette[i % len(palette)] for i, dev in enumerate(all_devices)}

    for ax, ((table_name, base_col), grp) in zip(axes_flat, groups):
        devices = grp["device_label"].unique()

        for device in devices:
            dev_grp = grp[grp["device_label"] == device].sort_index()
            color = device_colors[device]

            ax.fill_between(dev_grp.index, dev_grp["roll_min"], dev_grp["roll_max"],
                            alpha=0.15, color=color)
            ax.plot(dev_grp.index, dev_grp["roll_mean"], color=color, linewidth=1.5, linestyle="-")
            ax.plot(dev_grp.index, dev_grp["roll_median"], color=color, linewidth=1.5, linestyle="--", alpha=0.8)

        ax.set_title(f"{table_name}\n{base_col}", fontsize=9)
        ax.tick_params(labelsize=7)
        ax.grid(True, alpha=0.3)
        for label in ax.get_xticklabels():
            label.set_rotation(30)
            label.set_ha("right")

        # Per-subplot legend: which color is which device
        device_handles = [
            Line2D([0], [0], color=device_colors[d], linewidth=2, label=d if d else "device")
            for d in devices
        ]
        if len(device_handles) > 1:  # no need to label a single device
            ax.legend(handles=device_handles, fontsize=6, loc="upper right", frameon=False)

    for j in range(n, len(axes_flat)):
        axes_flat[j].axis("off")

    role_legend = [
        Line2D([0], [0], color="#555555", linewidth=1.5, label="Mean"),
        Line2D([0], [0], color="#555555", linewidth=1.5, linestyle="--", alpha=0.8, label="Median"),
        mpatches.Patch(color="#555555", alpha=0.15, label="Min–Max range"),
    ]
    fig.legend(handles=role_legend, fontsize=9, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.02))
    # fig.suptitle("Rolling Range Over Time", fontsize=13, y=1.06)
    plt.tight_layout()
    plt.close(fig)
    return fig