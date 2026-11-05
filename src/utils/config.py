import yaml
from pathlib import Path
from typing import Dict, Union

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


class ConfigError(Exception):
    """The configuration file is missing, unreadable or has invalid values."""


def load_config(config_path: Union[str, Path]) -> Dict:
    """
    טעינת קובץ הקונפיגורציה
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except OSError as e:
        raise ConfigError(f"Cannot read config file {config_path}: {e}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {config_path}: {e}") from e
    if not isinstance(config, dict):
        raise ConfigError(f"{config_path}: the top level must be a mapping of sections")
    return config
