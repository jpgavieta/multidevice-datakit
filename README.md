# MultiDevice DataToolkit

A python-based portable and customizable data processing pipeline to notebook-based html viewer (using juypter-viewer) for thee variable validation and statistical summarization of multiple devices.

The **etl (extract transform load) data pipeline** standardizes data variables, validates data types, and categorizes variables into usable dataframes (e.g. builds a GIS dataframe for mapping) — ready for data anlaysis and visualization between devices. 

The etl logic based on `device_types` as separate streams of data, not based on participants. 

It is expandable for more device types, which each require its own custom  parser. 

## Data Flow from Multiple Devices

The data pipeline starts from whereever the data is kept (either shared folder per device type, the cloud API of each device, or a database table of the device type). It is triggered upon command via `load.py` that tells `extract.py` to pull data from wherever, `transform.py` applies the parser logic specific to device, and returns an organized and subdivided dataframe per device.  

[![Flow of Data from Multiple Devices](multidevice_dataflow.png)](multidevice_dataflow.png)
---

## Structure of this Repository

```
/
├── .vscode/tasks.json      ## Protoype mode: mounts onto shared file cloud, does not keep any local copies
|                             
├── src/   
|   ├── __init__.py   
|   ├── utils.py                # Global functions (column type autodetection logic based on entire df not per row)
|   |            
|   └── etl/                ## Extract Transform Load Logic ----------------------------------------------------
│       ├── __init__.py        
|       ├── extract.py          # Reads raw data (current method: reads files; later upgrade: fetch apis)
|       ├── transform.py        # Applies parser (device-agnostic and extract-agnostic)
|       └── parsers/                # Builds dfs (device-specific)
|           ├── __init__.py      
|           ├── atmotube.py      
|           ├── ponyopi.py       
|           └── fitbit.py            
|      
├── notebooks/              ## Simple Vizualization of Available Data -------------------------------------------
|   └── howto.ipynb             # Explains how to see and retrieve the data
|   └── analysis.ipynb          # Analyses the data for all available devices 

| 
├── environment.yml             
|                     
└── docs/                       # Documentation per device
    ├── Atmotube_datasheet.md
    └── etc.
```

 
