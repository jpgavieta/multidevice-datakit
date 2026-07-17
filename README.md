# MultiDevice Datakit

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
- *Visualizes*: Provides non-technical abilities to visualize the data — internal-facing DB dashboard via Grafana (planned) and public-facing analytical reports via GitHub Pages (`docs/`) — separate from the automated pipeline.

2. **Why does this exists?**

Built specifically for a small-scale research (sole maintainer, some dozen devices) where heavy ETL frameworks (Meltano, Iceberg) are overkill. It delivers the smallest, most maintainable system that ensures reproducibility and allows easy extension to new device types without modifying core logic.


---

## Data Flow from Multiple Devices

The data pipeline starts from whereever the data is kept. It is triggered upon command via `load.py` that tells `extract.py` to pull data from wherever, `transform.py` applies the parser logic specific to device, and returns an organized and subdivided dataframe per device.  

[![Flow of Data from Multiple Devices](multidevice_dataflow.png)](multidevice_dataflow.png)
---

## Structure of this Repository

```
./
├── README.md
│
├── quarto.yml                    # for public-facing data reports
│                   
│                              ## DEV SETTINGS   
├── .gitignore          
├── pyproject.toml                # python packaged data building tools
├── environment.yml               # conda environment for python+system-level libraries (not pip installable) 
├── .env                          # gitignored — DB connection vars, Grafana admin creds
│
├── config/ 
│   ├── devices.yml               # device registry + site→credential mapping
│   └── schedule.yml              # human-editable schedule config (which job, how often)
│~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
│
├── deploy/                   ## DB+VIZ DEPLOYMENT
│   ├── docker-compose.yml         # Postgres+PostGIS, Grafana, ETL — defined as services
│   │
│   ├── postgres/
│   │   └── init/
│   │       └── 001_enable_postgis.sql   # runs once on first container start
│   │      
│   └── grafana/
│       ├── grafana-data/          # gitignored — Grafana's own sqlite db (users, sessions, dashboard state)
│       ├── provisioning/
│       │   ├── datasources/
│       │   │   └── postgres.yml   # auto-registers the Postgres+PostGIS datasource on boot
│       │   └── dashboards/
│       │       └── dashboards.yml # points Grafana at dashboard-json/ to load on boot (NOTE: allowUIUpdates: true for drag-n-drop GUI edits)
│       │   │   
│       ├── dashboard-json/        # after designing a dashboard in GUI, json export and git commit it here to save it as a snapshop (allows for dashboard configs to survive redeployment)
│       │   ├── EX: body_health.json
│       │   ├── EX: air_quality.json
│       │   └── EX: gis_location.json
│       │      
│       └── provision_access.py     # idempotent script: creates Teams (e.g. "Internal", "Participants"),
│                                   # sets org roles, assigns folder permissions via Grafana HTTP API
│                                   # — run once per environment (local, then Alliance) so access setup
│                                   # isn't manual click-ops that has to be redone on deploy
│
│~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
│                               ## ELT+ETL PIPELINE 
├── src/
│   ├── main.py                    # ENTRY POINT: starts the scheduler once and stays live (long running)
│   │
│   ├── scheduler/                  
│   │   ├── __init__.py
│   │   ├── scheduler.py            # builds APScheduler instance, loads jobs from schedule.yml
│   │   └── jobs.py                 # wraps E→T→L pipeline calls as schedulable job functions; tenacity retry/backoff in here
│   │
│   ├── general/
│   │   ├── __init__.py
│   │   ├── utils.py                # shared logic (e.g. column type autodetection), includes pipeline_runs health queries
│   │   ├── device_registry.py      # loads/validates devices.yml
│   │   └── run_logger.py           # writes to pipeline_runs table
│   │
│   ├── extract/
│   │   ├── __init__.py
│   │   ├── extract.py              # PULLS APIS: 
│   │   │                           #   - threaded per-device pulls, rate-limit aware
│   │   │                           #   - invoked by scheduler/jobs.py
│   │   ├── clients/
│   │   │   ├── __init__.py
│   │   │   ├── atmotube_client.py
│   │   │   └── fitbit_client.py
│   │   │
│   │   ├── scripts/                # used to debug device onboarding + data init process
│   │   │   └── ...
│   │   │
│   │   └── config/
│   │       ├── __init__.py
│   │       ├── tokens.py           # resolves site → env var name → secret
│   │       ├── fitbit_tokens.py    
│   │       └── secrets/            # gitignored — everything under here, no exceptions
│   │           ├── fitbit/
│   │           │   └── ...
│   │           └── atmotube/
│   │               ├── ...
│   │               └── backfill/
│   │                   └── ...     # all raw CSVs from Atmotubes since May
│   │
│   ├── transform/
│   │   ├── __init__.py
│   │   ├── transform.py            # APPLIES PARSERS: 
│   │   │                           #   - parthreaded per-device parsing
│   │   │                           #   - standardizes to UTC datetime
│   │   │                           #   - anonymization/pseudonymization step
│   │   ├── parsers/
│   │   │   ├── __init__.py
│   │   │   ├── atmotube.py
│   │   │   └── fitbit.py
│   │   └── utils.py
│   │
│   └── load/
│       ├── __init__.py
│       ├── load.py                 # PUSHES TO DB:
│       │                           #   - loads both raw (API pulls as JSONB) AND processed data (participant keyed)
│       │                           #   - single serialized write step 
│       │                           #   - upserts (update+insert), auto-adds new row if doesnt exist / auto-updates existing row if theres conflict 
│       ├── schema.sql              # source of truth: devices, participants, device_assignments, pipeline_runs, readings tables — PostGIS DDL
│       └── migrations/             # DB — schema change history
│           ├── EX: 0001_init_schema.sql
│           └── EX: 0002_add_participant_view.sql
│
│~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
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
    └── notify.py                    # email/Slack alert: 
                                     #  - fires on pipeline_runs failure
                                     #  - triggered from within scheduler/jobs.py after a failed run
```


# How to setup dev environment (fresh machine / new teammate)

## 1. Clone the repo
```shell
git clone <repo-url>
cd multidevice_dataToolkit
```

## 2. Create the conda env — this also installs the package (via the -e .[docs] line inside environment.yml)
```shell
conda env create -f environment.yml
conda activate multidevice_dataToolkit
```

## 3. Set up local secrets
```shell
cp .env.example .env
# → fill in .env with real DB creds, Fitbit/Atmotube client secrets, etc.
```

# 4. Bring up the local Postgres+PostGIS + Grafana stack
```shell 
cd deploy
docker compose up -d
```

# 5. Sanity check the package installed correctly
```shell
python -c "import extract; print(extract.__file__)"
```