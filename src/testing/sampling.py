import math
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.utils.config import ConfigError

# Keys of the testing.sampling section in config.yaml
COUNT_KEY = "measurements_count"
DURATION_KEY = "total_duration_seconds"
FREQUENCY_KEY = "sampling_frequency_hz"

# Relative tolerance for comparing floats: 0.1 * 30 is 3.0000000000000004, not 3.0
_REL_TOLERANCE = 1e-9


@dataclass(frozen=True)
class SamplingConfig:
    """
    How many measurements to take and how fast. The three values are linked:
    ``count = duration_s * frequency_hz``. Measurement ``i`` is scheduled at ``i / frequency_hz``
    seconds after the start, so the last one starts at ``(count - 1) / frequency_hz``, one interval
    before ``duration_s``.

    :ivar count: Number of measurements.
    :ivar duration_s: Total test duration in seconds: ``count`` intervals of ``1 / frequency_hz``.
    :ivar frequency_hz: Measurements per second.
    """
    count: int
    duration_s: float
    frequency_hz: float

    @property
    def interval_s(self) -> float:
        """
        :returns: Seconds between the starts of two consecutive measurements.
        """
        return 1 / self.frequency_hz

    @classmethod
    def from_values(cls, count: Optional[int] = None, duration_s: Optional[float] = None,
                    frequency_hz: Optional[float] = None) -> "SamplingConfig":
        """
        Creates the configuration from any two of the three values and computes the third.
        If all three are given, they must agree.

        :param count: Number of measurements, or ``None`` to compute it.
        :param duration_s: Total test duration in seconds, or ``None`` to compute it.
        :param frequency_hz: Measurements per second, or ``None`` to compute it.
        :returns: The complete configuration.
        :raises ConfigError: Fewer than two values are given, a value is invalid, the three values
            contradict each other, or duration and frequency do not give a whole number of measurements.
        """
        if count is not None:
            _check_count(count)
        if duration_s is not None:
            _check_positive_number(DURATION_KEY, duration_s)
        if frequency_hz is not None:
            _check_positive_number(FREQUENCY_KEY, frequency_hz)

        given = sum(value is not None for value in (count, duration_s, frequency_hz))
        if given < 2:
            raise ConfigError(f"Sampling: set at least two of {COUNT_KEY}, {DURATION_KEY}, {FREQUENCY_KEY}")

        if count is None:
            exact_count = duration_s * frequency_hz
            count = round(exact_count)
            if not math.isclose(count, exact_count, rel_tol=_REL_TOLERANCE):
                raise ConfigError(f"Sampling: {DURATION_KEY}={duration_s} x {FREQUENCY_KEY}={frequency_hz} "
                                  f"= {exact_count} measurements, which is not a whole number")
            _check_count(count)
        elif duration_s is None:
            duration_s = count / frequency_hz
        elif frequency_hz is None:
            frequency_hz = count / duration_s
        elif not math.isclose(count, duration_s * frequency_hz, rel_tol=_REL_TOLERANCE):
            raise ConfigError(f"Sampling: {COUNT_KEY}={count} contradicts {DURATION_KEY}={duration_s} x "
                              f"{FREQUENCY_KEY}={frequency_hz} = {duration_s * frequency_hz}; set only two of them")

        return cls(count, float(duration_s), float(frequency_hz))

    @classmethod
    def from_config(cls, config: Dict) -> "SamplingConfig":
        """
        Creates the configuration from the ``testing.sampling`` section of config.yaml.

        :param config: Configuration as returned by :func:`src.utils.config.load_config`.
        :returns: The complete configuration.
        :raises ConfigError: The section is missing or its values are invalid (see :meth:`from_values`).
        """
        section = (config.get("testing") or {}).get("sampling")
        if not isinstance(section, dict):
            raise ConfigError("The 'testing.sampling' section is missing")
        return cls.from_values(section.get(COUNT_KEY), section.get(DURATION_KEY), section.get(FREQUENCY_KEY))


def _check_count(count: Any) -> None:
    """
    :param count: Value to check.
    :raises ConfigError: ``count`` is not a whole number of at least 1.
    """
    # bool is a subclass of int in Python, so 'true' would otherwise pass as 1
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ConfigError(f"Sampling: {COUNT_KEY} must be a whole number of at least 1, got {count!r}")


def _check_positive_number(key: str, value: Any) -> None:
    """
    :param key: Config key of the value, used in the error message.
    :param value: Value to check.
    :raises ConfigError: ``value`` is not a finite number greater than 0.
    """
    # YAML reads '.inf' and '.nan' as numbers, so they are rejected explicitly
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ConfigError(f"Sampling: {key} must be a finite number greater than 0, got {value!r}")
