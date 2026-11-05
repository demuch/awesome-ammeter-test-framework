import statistics
from dataclasses import dataclass
from typing import Optional, Sequence

from src.testing.sampling import SampleSeries

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
