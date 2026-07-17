# extract/__init__.py
from .extract import extract_all_devices # script ochestrator

# import os
# from pathlib import Path
# from dotenv import load_dotenv

# BASE_DIR = Path(__file__).resolve().parent
# secrets_dir = BASE_DIR / 'secrets'

# # Load Fitbit Credentials
# fitbit_env = secrets_dir / 'fitbit' / '.env.access'
# if not load_dotenv(dotenv_path=fitbit_env):
#     # Optional: Only raise if you strictly require this file at startup
#     # raise FileNotFoundError(f"Fitbit credentials not found at {fitbit_env}")
#     pass

# # Load Atmotube Credentials
# atmotube_env = secrets_dir / 'atmotube' / '.env.access'
# if not load_dotenv(dotenv_path=atmotube_env):
#     # raise FileNotFoundError(f"Atmotube credentials not found at {atmotube_env}")
#     pass


### How to use in code:

# import extract  # Loads both .env.access files automatically
# import yaml
# from yaml_env_tag import add_env_tag

# # Load devices.yml
# with open('config/devices.yml', 'r') as f:
#     loader = add_env_tag(yaml.SafeLoader)
#     config = yaml.load(f, Loader=loader)

# # Access data
# fitbit_user = os.getenv("FITBIT_KOL_01")
# atmotube_mac = os.getenv("ATMOTUBE_MAC_01")   