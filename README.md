# MultiDevice DataToolkit

> 🚧 Work in progress !
> This is an evolving research data pipeline, not a finished product. 
> Structure and scope are actively changing as new devices and features come online.

A Python-based, portable, and customizable pipeline for pulling, standardizing, and storing multi-device research data — combining an
**API scheduler**, an **ETL pipeline**, and a **database deployer** into one lightweight data warehouse.

Built for a multi-site study tracking environmental exposure (Atmotube air quality sensors) and biometric data (Fitbit / Google Health) across rotating device assignments and multiple participants — but designed to be extended to any new device type with its own API and parser.

1. **What does this project do?**

- *Ingests*: Schedules daily extraction from each device's cloud API (Atmotube, Google Health/Fitbit), on a daily cron schedule, with built-in rate limiting. 
- *Processes*: Standardizes and validates per device type — parsing raw API responses into clean, typed, timezone-normalized dataframes ready for analysis.
- *Stores*: Maintains a remote PostgreSQL + PostGIS database (via Docker) for raw + processed data with device/participant assignment tracking to reconcile data across a rotating-device study design.
- *Visualizes*: Provides non-technical abilities to visualize the data — internal-facing DB dashboard via Metabase (planned) and public-facing analytical reports via GitHub Pages (`docs/`) — eparate from the automated pipeline.

2. **Why does this exists?**

Built specifically for a small-scale research (sole maintainer, few dozens of devices) where heavy ETL frameworks (Meltano, Iceberg) are overkill. It delivers the smallest, most maintainable system that ensures reproducibility and allows easy extension to new device types without modifying core logic.


---

## Data Flow from Multiple Devices

The data pipeline starts from whereever the data is kept. It is triggered upon command via `load.py` that tells `extract.py` to pull data from wherever, `transform.py` applies the parser logic specific to device, and returns an organized and subdivided dataframe per device.  

[![Flow of Data from Multiple Devices](multidevice_dataflow.png)](multidevice_dataflow.png)
---

## Structure of this Repository

```
multidevice_dataToolkit/
├── pyproject.toml
├── .env                          # gitignored — actual secret client credentials + DB connection vars
├── .env.example                  # committed — variable names only
├── .gitignore
├── README.md
├── requirements.txt
├── crontab.txt                   # documented cron schedule, for api fetching reference
├── quarto.yml                    # quart notebook settings, for public-facing data reports
│
├── deploy/    # DATABASE VIZ ========================================================================================================== 
│   ├── docker-compose.yml         # Postgres+PostGIS, Metabase, defined as services
│   ├── postgres/
│   │   └── init/
│   │       └── 01_enable_postgis.sql   # runs once on first container start
│   └── metabase/
│       └── metabase-data/          # Metabase's own UI app
│
├── config/                   
│   └── devices.yaml               # device registry + site→credential mapping
│
├── src/        # ETL PIPELINE ===========================================================================================================
│   ├── main.py                    # entry point: loop over devices.yaml, run E→T→L
│   │
│   ├── general/
│   │   ├── __init__.py
│   │   ├── utils.py                # shared logic (e.g. column type autodetection), includes pipeline_runs health queries
│   │   ├── device_registry.py      # loads/validates devices.yaml
│   │   └── run_logger.py           # writes to pipeline_runs table
│   │
│   ├── extract/
│   │   ├── __init__.py
│   │   ├── extract.py              # threaded per-device pulls, rate-limit aware
│   │   ├── clients/
│   │   │   ├── __init__.py
│   │   │   ├── atmotube_client.py
│   │   │   └── fitbit_client.py
│   │   ├── config/
│   │   │   ├── __init__.py
│   │   │   ├── tokens.py           # resolves site → env var name → secret
│   │   │   └── secrets/            # gitignored — everything under here, no exceptions
│   │   │       ├── fitbit/
│   │   │       │   ├── client_secret.json # shared OAuth client, one file
│   │   │       │   ├── accounts.yml       # device_id: google_account 
│   │   │       │   └── tokens/      
│   │   │       │       ├── fitbit_ko1_01.json
│   │   │       │       ├── fitbit_ko1_02.json
│   │   │       │       └── ...
│   │   │       └── atmotube/
│   │   │           └── ...
│   │   └── utils.py
│   │
│   ├── transform/
│   │   ├── __init__.py
│   │   ├── transform.py            # per-device parsing, UTC conversion
│   │   ├── parsers/
│   │   │   ├── __init__.py
│   │   │   ├── atmotube.py
│   │   │   └── fitbit.py
│   │   └── utils.py
│   │
│   └── load/
│       ├── __init__.py
│       ├── load.py                 # single serialized write step, upserts
│       ├── schema.sql              # devices, participants, device_assignments, pipeline_runs, readings tables # DB —  now includes PostGIS-specific DDL
│        └── migrations/            # DB — schema change history, see below
│            ├── 0001_init_schema.sql
│            └── 0002_add_participant_view.sql
│                
│
├── docs/                           # GitHub Pages — manual notebooks + html rendering helpers in utils
│   ├── atmotube
│   │   ├── datasheet.md
│   │   └── report.ipynb
│   ├── __init__.py
│   ├── manual.ipynb
│   ├── stats.py
│   └── utils.py                    
│
└── notifications/
    └── notify.py                    # email/Slack alert on pipeline_runs failure
```

 
