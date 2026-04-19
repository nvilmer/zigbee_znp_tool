import logging
import sys
from pathlib import Path
import configparser

# get config path
config_path = Path(Path.home() / ".znp" / "config.ini")
config = configparser.ConfigParser()

# create ~/.znp/config.ini if it doesn't exist with log level'
if not config_path.exists():
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config.add_section("settings")
    config.set("settings", "log_level", "INFO")
    with open(config_path, 'w') as configfile:
        config.write(configfile)
else:
    config.read(config_path)

# setup logger
log_level = config.get("settings", "log_level", fallback="INFO").upper()

# Configure the root logger so that library logs (zigpy, etc.) are captured
root_log = logging.getLogger()
root_log.setLevel(log_level)

# Create the console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(log_level)
formatter = logging.Formatter('%(levelname)s: %(message)s')
console_handler.setFormatter(formatter)

# Clear existing handlers if any, then add our console handler to the root
root_log.handlers = []
root_log.addHandler(console_handler)

# Get our specific logger for the 'znp' package
log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

# Zigbee database path
data_base_path = Path(Path.home() / ".znp" / "zigbee.db")
# We don't touch the file anymore, let zigpy create and initialize it correctly
