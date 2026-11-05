from pathlib import Path
from typing import Dict, Union

from .ammeter import load_ammeters
from ..utils.config import DEFAULT_CONFIG_PATH, load_config

class AmmeterTestFramework:
    def __init__(self, config_path: Union[str, Path] = DEFAULT_CONFIG_PATH):
        """
        Loads the configuration and creates the ammeters described in it.

        :param config_path: Path to the YAML configuration file; by default ``config/config.yaml``
            in the project root, independent of the current directory.
        :raises ConfigError: The file cannot be read or has invalid values.
        """
        self.config = load_config(config_path)
        self.ammeters = load_ammeters(self.config)

    def run_test(self, ammeter_type: str) -> Dict:
        pass
