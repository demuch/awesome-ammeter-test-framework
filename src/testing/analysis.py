import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Sequence, Tuple

from src.testing.sampling import SampleSeries
from src.utils.config import ConfigError

# Names of all metrics, in report order; also the allowed values of analysis.statistical_metrics
METRICS = ("mean", "median", "stdev", "min", "max", "relative_spread")


@dataclass(frozen=True)
class ValueStats:
    """
    Statistical metrics of a set of numbers. A metric that cannot be computed for the given data is ``None``.

    :ivar count: How many numbers were analysed.
    :ivar mean: Average; ``None`` if there are no numbers.
    :ivar median: Middle value after sorting (average of the two middle values for an even count);
        ``None`` if there are no numbers.
    :ivar stdev: Sample standard deviation (divides by ``count - 1``, because a series is only a part of
        what the ammeter could return); ``None`` for fewer than two numbers.
    :ivar min: Smallest number; ``None`` if there are no numbers.
    :ivar max: Largest number; ``None`` if there are no numbers.
    :ivar relative_spread: ``stdev / |mean|``, so series with very different scales can be compared;
        ``None`` if ``stdev`` is ``None`` or the mean is 0.
    """
    count: int
    mean: Optional[float]
    median: Optional[float]
    stdev: Optional[float]
    min: Optional[float]
    max: Optional[float]
    relative_spread: Optional[float]

    @classmethod
    def from_values(cls, values: Sequence[float]) -> "ValueStats":
        """
        Computes all metrics.

        :param values: Numbers to analyse; may be empty.
        :returns: The metrics.
        """
        if not values:
            return cls(0, None, None, None, None, None, None)
        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if len(values) >= 2 else None
        relative_spread = stdev / abs(mean) if stdev is not None and mean != 0 else None
        return cls(len(values), mean, statistics.median(values), stdev, min(values), max(values), relative_spread)


@dataclass(frozen=True)
class TestResult:
    """
    Everything known about one test run: the measurements and their analysis.

    :ivar series: All measurements with their timing.
    :ivar values: Metrics of the successful measurement values.
    :ivar response_time: Metrics of how long the ammeter took to answer, in seconds, over all requests.
    """
    __test__ = False  # Not a test class, although the name starts with "Test" (stops pytest from collecting it)

    series: SampleSeries
    values: ValueStats
    response_time: ValueStats

    @property
    def ammeter(self) -> str:
        """
        :returns: Name of the tested ammeter.
        """
        return self.series.ammeter

    @property
    def success_rate(self) -> float:
        """
        :returns: Share of successful measurements, from 0.0 to 1.0.
        """
        return self.values.count / len(self.series.samples)


def analyze(series: SampleSeries) -> TestResult:
    """
    Computes the metrics of a sampling series. Failed measurements have no value, so they are left out
    of the value metrics, but their response time is included: a slow failure is still a slow answer.

    :param series: The measured series.
    :returns: The series together with its metrics.
    """
    durations = [s.measurement.duration_s for s in series.samples]
    return TestResult(series, ValueStats.from_values(series.values), ValueStats.from_values(durations))


def report_metrics_from_config(config: Dict) -> Tuple[str, ...]:
    """
    Reads which metrics the report shows from ``analysis.statistical_metrics``. All metrics are always
    computed; this setting only selects what is printed.

    :param config: Configuration as returned by :func:`src.utils.config.load_config`.
    :returns: Metric names in report order; all of :data:`METRICS` if the setting is missing or empty.
    :raises ConfigError: The setting is not a list, or contains a name that is not in :data:`METRICS`.
    """
    selected = (config.get("analysis") or {}).get("statistical_metrics")
    if not selected:
        return METRICS
    if not isinstance(selected, list):
        raise ConfigError(f"analysis.statistical_metrics must be a list of metric names, got {selected!r}")
    unknown = [name for name in selected if name not in METRICS]
    if unknown:
        raise ConfigError(f"analysis.statistical_metrics: unknown metric(s) {unknown}; known: {list(METRICS)}")
    return tuple(name for name in METRICS if name in selected)


def format_report(result: TestResult, metrics: Sequence[str] = METRICS) -> str:
    """
    Formats a test result as readable text for the console.

    :param result: The analysed test run.
    :param metrics: Which metrics to show for values and response time, see :data:`METRICS`.
    :returns: The report, several lines without a trailing newline.
    """
    series, timing = result.series, result.series.timing
    total, ok = len(series.samples), result.values.count
    # A single measurement has no actual frequency
    actual = f"{timing.actual_frequency_hz:.2f} Hz actual; " if timing.actual_frequency_hz is not None else ""
    lines = [
        f"=== {result.ammeter}: {total} measurements, {ok} ok, {total - ok} failed ({result.success_rate:.0%}) ===",
        f"Values (A)     {_format_stats(result.values, metrics, lambda v: f'{v:.4g}')}",
        f"Response time  {_format_stats(result.response_time, metrics, lambda v: f'{v * 1000:.2f} ms')}",
        f"Timing         {series.config.frequency_hz:g} Hz planned, {actual}"
        f"lag mean {timing.mean_lag_s * 1000:.1f} ms, max {timing.max_lag_s * 1000:.1f} ms; "
        f"{timing.late_count} late, schedule shifted by {timing.schedule_shift_s * 1000:.1f} ms",
    ]
    if timing.min_interval_s is not None:
        lines.append(f"               interval between measurements {timing.min_interval_s * 1000:.1f}"
                     f"-{timing.max_interval_s * 1000:.1f} ms")
    if series.failed:
        # The same error is usually repeated many times; show each reason once with its count
        reasons = Counter(s.measurement.error for s in series.failed).most_common(3)
        lines.append("Failures       " + "; ".join(f"{count}x {error}" for error, count in reasons))
    return "\n".join(lines)


def _format_stats(stats: ValueStats, metrics: Sequence[str], fmt: Callable[[float], str]) -> str:
    """
    :param stats: Metrics to show.
    :param metrics: Which metrics to show, in this order.
    :param fmt: Formats one value; not used for ``relative_spread``, which is shown in percent.
    :returns: One line, or ``"no data"`` if there were no numbers.
    """
    if stats.count == 0:
        return "no data"
    parts = []
    for name in metrics:
        value = getattr(stats, name)
        if value is None:
            text = "n/a"
        elif name == "relative_spread":
            text = f"{value:.1%}"
        else:
            text = fmt(value)
        parts.append(f"{name} {text}")
    return "  ".join(parts)
