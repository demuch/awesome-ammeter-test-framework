from pathlib import Path
from typing import Optional, Union

from .ammeter import load_ammeters
from .sampling import SampleSeries, SamplingConfig, sample
from ..utils.config import DEFAULT_CONFIG_PATH, load_config

class AmmeterTestFramework:
    def __init__(self, config_path: Union[str, Path] = DEFAULT_CONFIG_PATH):
        """
        Loads the configuration and creates the ammeters and the sampling settings described in it,
        so configuration errors show up before any test runs.

        :param config_path: Path to the YAML configuration file; by default ``config/config.yaml``
            in the project root, independent of the current directory.
        :raises ConfigError: The file cannot be read or has invalid values.
        """
        self.config = load_config(config_path)
        self.ammeters = load_ammeters(self.config)
        self.sampling = SamplingConfig.from_config(self.config)

    def run_test(self, ammeter_type: str, sampling: Optional[SamplingConfig] = None) -> SampleSeries:
        """
        Runs one sampling series on one ammeter.

        :param ammeter_type: Ammeter name as used in config.yaml, e.g. ``"greenlee"``.
        :param sampling: Sampling settings for this run; by default the ``testing.sampling`` section of the config.
        :returns: All measurements of the series with their timing.
        :raises ValueError: There is no ammeter with this name in the configuration.
        """
        if ammeter_type not in self.ammeters:
            raise ValueError(f"Unknown ammeter {ammeter_type!r}; configured: {list(self.ammeters)}")
        return sample(self.ammeters[ammeter_type], sampling or self.sampling)
