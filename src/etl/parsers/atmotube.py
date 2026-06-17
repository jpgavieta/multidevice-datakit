from functools import reduce
import pandas as pd

from src.utils import (
    build_gis_df,
    add_timezone_col,
    get_cols,
    rename_cols,
)


# ============================================================================================================
# Df builders 

def build_pm_df(df): # PM sensor = Sensirion SPS30
    pm_df = get_cols(df, ["datetime", "pm", "µg/m³", "particle", "size"], ["ppm"])
    pm_df = rename_cols(pm_df,
        ["pm", "2", "5"],   "pm2_5_ugm3_atm",
        ["pm", "10"],       "pm10_ugm3_atm",
        ["pm", "1"],        "pm1_0_ugm3_atm",
        ["0", "5"],         "pm0_5_um_count",
        ["2", "5"],         "pm2_5_um_count",
        ["10"],             "pm10_um_count",
        ["1"],              "pm1_0_um_count",
        ["size"],           "pmsize_nm_avg",
        silent=True
    )
    if "pmsize_nm_avg" in pm_df.columns:
        pm_df["pmsize_um_avg"] = pm_df["pmsize_nm_avg"] / 1000

    if not any(c in pm_df.columns for c in ["pm0_5_um_count", 
                                            "pm2_5_um_count", 
                                            "pm10_um_count"]):
        print("No raw particle count data available.") # Only PRO 2 has extended PM data

    return pm_df


def build_weather_df(df): # Barometer sensor = Bosch BME280 
    weather_df = get_cols(df, ["datetime", "temp", "hum", "press", "aqs"])
    return rename_cols(weather_df,
        ["aqs"],   "aqs_total", # AQS aggregate = PM + TVOC + CO2 + NOx
        ["temp"],  "temp_c",
        ["hum"],   "hum_pct",
        ["press"], "press_hpa"
    )


def build_gas_df(df): # VOC sensor = Sensirion SGP40
    gas_df = get_cols(df, ["datetime", "tvoc", "nox", "co2"])
    return rename_cols(gas_df,
        ["tvoc", "ppm"],    "tvoc_ppm",
        ["tvoc", "index"],  "tvoc_index",
        ["nox", "index"],   "nox_index",
        ["co2", "ppm"],     "co2_ppm"
    )


def build_sat_df(df):
    sat_df = get_cols(df, ["datetime", "gps", "position", "gnss", "sat"], ["phone"])
    sat_df = rename_cols(sat_df,
        ["position"],               "position_error_m",
        ["sat", "view"],            "sat_view_count",
        ["sat", "fix"],             "sat_used_count",
        ["gnss", "snr", "0-19"],    "sat_lowsignal_count",
        ["gnss", "snr", "20-49"],   "sat_medsignal_count",
        ["gnss", "snr", "50-99"],   "sat_highsignal_count",
        ["gnss", "snr", "avg"],     "sat_signal_avg",
        silent=True
    )

    if not any(c in sat_df.columns for c in ["sat_view_count", 
                                            "sat_used_count",
                                            "sat_lowsignal_count",
                                            "sat_medsignal_count",
                                            "sat_highsignal_count",
                                            "sat_signal_avg"    
                                            ]):
        print("No satellite data available.") # Only PRO 2 has extended sat data

    return sat_df

def build_phone_df(df):
    phone_df = get_cols(df, ["datetime", "motion", "phone", "batt", "charg"])

    if "Phone GPS" in df.columns:
        phone_df['gps_phone_bool'] = df['Phone GPS'].map({'yes': True, 'no': False}) # Was the phone GPS currently used for this data point? (yes/no --> 1/0)
        phone_df = phone_df.drop(columns=["Phone GPS"]) 

    phone_df = rename_cols(phone_df, # Was the phone in motion? (yes/no --> 1/0)
        ["motion"], "motion_phone_bool",
    )
    phone_df = phone_df.replace({'yes': True, 'no': False}) # For any remaining yes/no columns (e.g. motion), convert to bools (1/0)

    phone_df = rename_cols(phone_df,
        ["batt"],  "battery_phone_pct",
        ["charg"], "charg_phone_raw"      # temp name before splitting into two bools
    )

    phone_df["charge_phone_bool"]   = phone_df["charg_phone_raw"].map({"no": False, "cd": False, "yes": True})   # Was the phone currently charging during data collection? (yes/no --> 1/0)
    phone_df["cooldown_phone_bool"] = phone_df["charg_phone_raw"].map({"no": False, "cd": True, "yes": False})   # Was the phone currently in cooldown AFTER charging (yes/no --> 1/0, cd (cooldown) --> 1, treated as a separate boolean since cooldown may impact phone's performance)
    phone_df = phone_df.drop(columns=["charg_phone_raw"])

    return phone_df

def build_txt_df(df):
    txt_df = get_cols(df, ["datetime", "notes"])
    return rename_cols(txt_df, ["notes"],   "user_notes")


# ============================================================================================================
# Top-level parser 

def parse(df: pd.DataFrame) -> dict:
    df = df.copy()

    df = add_timezone_col(df) # Standardizes datetime, latitude, longotide and adds timzezone
                            # Includes detect_utc_col and detect_latlon_cols internally

    dfs = {
        "gis":      build_gis_df(df), # Actually pulls from shared utils.py
        "pm":       build_pm_df(df),
        "weather":  build_weather_df(df),
        "gas":      build_gas_df(df),
        "phone":    build_phone_df(df),
        "sat":      build_sat_df(df),
        "txt":      build_txt_df(df),
    }

    dfs["all"] = reduce(
        lambda left, right: pd.merge(left, right, on="datetime", how="left"),
        [dfs[k] for k in ("gis", "pm", "weather", "gas", "phone", "sat", "txt")]
    )

    return dfs

# Example: from src.parsers.atmotube import parse
#          dfs = parse(df)
#          dfs["pm"]       # PM sub-dataframe
#          dfs["all"]      # fully merged dataframe