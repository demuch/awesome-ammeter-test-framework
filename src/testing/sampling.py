import math
import statistics
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from src.testing.ammeter import Ammeter, Measurement
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


@dataclass(frozen=True)
class Sample:
    """
    One measurement of a series together with its timing.

    :ivar index: Position in the series, starting at 0.
    :ivar scheduled_s: When the measurement should have started, in seconds after the series start.
    :ivar started_s: When it actually started, in seconds after the series start.
    :ivar late: ``True`` if the scheduled moment had already passed when the measurement could start,
        because the previous one took longer than the interval. The rest of the schedule is then
        shifted by the delay.
    :ivar measurement: The measurement itself.
    """
    index: int
    scheduled_s: float
    started_s: float
    late: bool
    measurement: Measurement

    @property
    def lag_s(self) -> float:
        """
        :returns: How much later than scheduled the measurement started, in seconds.
        """
        return self.started_s - self.scheduled_s


@dataclass(frozen=True)
class TimingStats:
    """
    How closely a series followed its schedule.

    :ivar actual_frequency_hz: Measured rate between the first and the last start, or ``None`` for one measurement.
    :ivar mean_lag_s: Average delay of a start against its scheduled moment, in seconds.
    :ivar max_lag_s: Largest delay of a start against its scheduled moment, in seconds.
    :ivar late_count: Number of measurements that started after their scheduled moment had passed.
    :ivar min_interval_s: Shortest time between two consecutive starts, or ``None`` for one measurement.
    :ivar max_interval_s: Longest time between two consecutive starts, or ``None`` for one measurement.
        Together with ``min_interval_s`` this shows local problems that the average frequency hides.
    :ivar schedule_shift_s: How much the schedule was shifted in total because of late measurements.
    """
    actual_frequency_hz: Optional[float]
    mean_lag_s: float
    max_lag_s: float
    late_count: int
    min_interval_s: Optional[float]
    max_interval_s: Optional[float]
    schedule_shift_s: float


@dataclass(frozen=True)
class SampleSeries:
    """
    Result of one sampling run on one ammeter.

    :ivar ammeter: Name of the ammeter.
    :ivar config: Sampling configuration that was used.
    :ivar started_at: Unix time when the series started.
    :ivar samples: All measurements in order; a tuple, so the frozen series cannot be changed.
    :ivar schedule_shift_s: How much the schedule was shifted in total because of late measurements.
    """
    ammeter: str
    config: SamplingConfig
    started_at: float
    samples: Tuple[Sample, ...]
    schedule_shift_s: float

    @property
    def values(self) -> Tuple[float, ...]:
        """
        :returns: Values of the successful measurements, in order.
        """
        return tuple(s.measurement.value for s in self.samples if s.measurement.ok)

    @property
    def failed(self) -> Tuple[Sample, ...]:
        """
        :returns: Samples whose measurement failed; the reason is in ``measurement.error``.
        """
        return tuple(s for s in self.samples if not s.measurement.ok)

    @property
    def timing(self) -> TimingStats:
        """
        :returns: How closely the series followed its schedule.
        """
        lags = [s.lag_s for s in self.samples]
        starts = [s.started_s for s in self.samples]
        intervals = [b - a for a, b in zip(starts, starts[1:])]
        actual_frequency_hz = (len(starts) - 1) / (starts[-1] - starts[0]) if starts[-1] > starts[0] else None
        return TimingStats(actual_frequency_hz, statistics.mean(lags), max(lags),
                           sum(s.late for s in self.samples),
                           min(intervals) if intervals else None,
                           max(intervals) if intervals else None,
                           self.schedule_shift_s)


def sample(ammeter: Ammeter, config: SamplingConfig,
           clock: Callable[[], float] = time.perf_counter,
           sleep: Callable[[float], None] = time.sleep) -> SampleSeries:
    """
    Takes ``config.count`` measurements, starting measurement ``i`` at ``i / config.frequency_hz``
    seconds after the start. Waiting until a fixed moment instead of sleeping a fixed interval keeps
    small delays from adding up. If a measurement takes longer than the interval, the next one starts
    immediately, is marked as late, and the rest of the schedule is shifted by the delay: no measurement
    is skipped and no burst of catch-up measurements is sent to a slow ammeter. Failed measurements
    are kept in the series and do not stop it.

    :param ammeter: Ammeter to measure.
    :param config: How many measurements to take and how fast.
    :param clock: Monotonic clock in seconds; replaceable in tests.
    :param sleep: Function that waits the given number of seconds; replaceable in tests.
    :returns: All measurements with their timing.
    """
    started_at = time.time()
    start = clock()
    samples = []
    shift_s = 0.0  # How much the schedule was moved because of late measurements
    for i in range(config.count):
        # Computed from the index, not by adding the interval repeatedly, so rounding errors do not add up
        scheduled_s = i / config.frequency_hz + shift_s
        wait_s = scheduled_s - (clock() - start)
        late = i > 0 and wait_s < 0
        if late:
            # Only a missed moment shifts the schedule; small wake-up delays of sleep() do not,
            # otherwise they would add up again
            shift_s -= wait_s
        elif wait_s > 0:
            sleep(wait_s)
        started_s = clock() - start
        samples.append(Sample(i, scheduled_s, started_s, late, ammeter.measure()))
    return SampleSeries(ammeter.name, config, started_at, tuple(samples), shift_s)
