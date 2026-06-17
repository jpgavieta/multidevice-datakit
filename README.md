# MultiDevice DataToolkit

A python-based data processing pipeline to notebook-based html viewer (using juypter-viewer) for the statistical summaries and validations of multiple devices.

The pipeline logic based on `device_types` as separate streams of data, not based on participants.

Doesn't keep local copies of the data.

---

## What's in here?

```
/
├── .vscode/tasks.json          #Protoype mode: mounts onto shared file cloud
|                             
├── src/   
|   ├── __init__.py   
|   ├── utils.py                # Global functions (column type autodetection logic based on entire df not per row)
|   |            
|   └── etl/                    # Extract, Transform, Load Logic --------------------------------------------------
│       ├── __init__.py
|       ├── extract.py          # Reads raw data (reads files now, fetchs apis later)
|       ├── transform.py        # Applies parser
|       └── parsers/            # Builds dfs
|           ├── __init__.py      
|           ├── atmotube.py      
|           ├── ponyopi.py       
|           └── fitbit.py            
|      
├── notebooks/                  # Vizualizes data as html report
|   └── main.ipynb 
| 
├── environment.yml             
|                     
└── docs/                       # Documentation per device
    ├── Atmotube_datasheet.md
    └── etc.
```

<a href="multidevice_dataflow.png">
  <img src="multidevice_dataflow.png" alt="Flow of Data" width="600" />
</a>   
