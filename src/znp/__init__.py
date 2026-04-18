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
log = logging.getLogger(__name__)
log_level = config.get("settings", "log_level")
log.setLevel(log_level)  # Set the base level high to capture everything
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)  # Only show INFO+ to the user by default
formatter = logging.Formatter('%(levelname)s: %(message)s')
console_handler.setFormatter(formatter)
log.addHandler(console_handler)
log.addHandler(logging.NullHandler())

