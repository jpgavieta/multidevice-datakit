import pandas as pd
from src.utils import get

# ============================================================================================================
# Helpers

def _get_numeric_cols(df):
    """Return all numeric columns except datetime, date, time."""
    skip = {"datetime", "date", "time"}
    return [
        col for col in df.columns
        if col not in skip and pd.api.types.is_numeric_dtype(df[col])
    ]

def _resolve_targets(dfs, df_names, skip):
    """Resolve which dfs to operate on."""
    if df_names:
        invalid = [n for n in df_names if n not in dfs]
        if invalid:
            print(f"df(s) not found: {invalid}. Available: {[k for k in dfs if k not in skip]}")
            return None
        return {n: dfs[n] for n in df_names}
    return {k: v for k, v in dfs.items() if k not in skip}

# ============================================================================================================
# Main

def report_loss(device, *df_names):
    """
    Reports data quality metrics: row counts, missing values, and coverage %.
    Includes a visual bar for coverage.
    """
    skip = {"all"}  # merged table — NaNs here come from the join, not real sensor dropout
    dfs = get(device)
    targets = _resolve_targets(dfs, df_names, skip)
    if targets is None:
        return

    print(f"{'df':<10} {'column':<25} {'rows':>8} {'missing':>8} {'coverage':>10}")
    print("─" * 68)

    for name, df in targets.items():
        total_rows = df.shape[0]
        for col in df.columns:
            if col in {"datetime", "date", "time"}:
                continue

            missing = df[col].isna().sum()
            coverage = (1 - missing / total_rows) * 100 if total_rows > 0 else 0.0

            bar_len = int(coverage / 10)
            bar = "█" * bar_len + "░" * (10 - bar_len)

            print(f"{name:<10} {col:<25} {total_rows:>8} {missing:>8} {coverage:>8.1f}%  {bar}")
        print()

# report_loss(device)              # all tables
# report_loss(device, "pm")        # just pm
# report_loss(device, "pm", "gas") # pm and gas


def plot_ranges(device, *df_names, window="10min", center="mean", figsize=(10, 4)):
    """
    Plots a range-area chart for each numeric column in the target df(s):
    a shaded band showing the rolling min/max envelope over time, with a
    rolling mean/median line drawn through it.
    """
    skip = {"all"}
    dfs = get(device)
    targets = _resolve_targets(dfs, df_names, skip)
    if targets is None:
        return

    for name, df in targets.items():
        numeric_cols = _get_numeric_cols(df)
        if not numeric_cols:
            continue

        has_time = "datetime" in df.columns
        if has_time:
            df = df.dropna(subset=["datetime"]).sort_values("datetime").set_index("datetime")
        else:
            df = df.reset_index(drop=True)

        x = df.index

        for col in numeric_cols:
            roll = df[col].rolling(window=window, min_periods=1)
            lower = roll.min()
            upper = roll.max()
            line = roll.mean() if center == "mean" else roll.median()

            fig, ax = plt.subplots(figsize=figsize)
            ax.fill_between(x, lower, upper, alpha=0.3, label=f"rolling min/max (window={window})")
            ax.plot(x, line, linewidth=1.2, label=f"rolling {center}")
            ax.set_title(f"{name} — {col}")
            ax.set_xlabel("datetime" if has_time else "index")
            ax.set_ylabel(col)
            ax.legend(loc="upper right", fontsize=8)
            fig.tight_layout()
            plt.show()