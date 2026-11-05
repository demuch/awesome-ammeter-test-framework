"""Tests of the statistical metrics and the text report."""
import pytest

from src.testing.analysis import METRICS, ValueStats, analyze, format_report, report_metrics_from_config
from src.testing.sampling import SamplingConfig, sample
from src.utils.config import ConfigError
from tests.conftest import StubAmmeter


def analysed(clock, count=5, durations=(), errors=()):
    """
    Samples a :class:`StubAmmeter` (values 0, 1, 2, ...) with the fake clock and analyses the series.

    :param clock: The fake clock.
    :param count: Number of measurements, at 10 Hz.
    :param durations: Duration of each measurement in seconds.
    :param errors: Indexes of measurements that fail.
    :returns: The analysed result.
    """
    config = SamplingConfig.from_values(count=count, frequency_hz=10)
    ammeter = StubAmmeter(clock, durations=durations, errors=errors)
    return analyze(sample(ammeter, config, clock=clock.now, sleep=clock.sleep))


# --- metrics ---

def test_metrics_of_known_data():
    """10, 11, 9, 10, 60: values worked out by hand; the median ignores the outlier, the mean does not."""
    stats = ValueStats.from_values([10, 11, 9, 10, 60])
    assert stats.count == 5
    assert stats.mean == pytest.approx(20)
    assert stats.median == pytest.approx(10)
    assert stats.stdev == pytest.approx(22.3719, rel=1e-4)  # sqrt(2002 / 4): sample stdev divides by n - 1
    assert (stats.min, stats.max) == (9, 60)
    assert stats.relative_spread == pytest.approx(22.3719 / 20, rel=1e-4)


def test_median_of_even_count_is_mean_of_middle_values():
    """For an even count the median is the average of the two middle values, not one of them."""
    assert ValueStats.from_values([4, 1, 3, 2]).median == pytest.approx(2.5)


@pytest.mark.parametrize("values, expected", [
    ([], dict(count=0, mean=None, median=None, stdev=None, min=None, max=None, relative_spread=None)),
    ([7.5], dict(count=1, mean=7.5, median=7.5, stdev=None, min=7.5, max=7.5, relative_spread=None)),
    ([3, 3, 3], dict(count=3, mean=3, median=3, stdev=0, min=3, max=3, relative_spread=0)),
    ([-1, 1], dict(count=2, mean=0, median=0, relative_spread=None)),
])
def test_metrics_edge_cases(values, expected):
    """No values, one value, identical values and a mean of 0 give None where a metric is undefined."""
    stats = ValueStats.from_values(values)
    for name, value in expected.items():
        assert getattr(stats, name) == (pytest.approx(value) if value is not None else None), name


def test_failed_measurements_excluded_from_values_but_not_from_response_time(clock):
    """Failures have no value, but a slow failure is still a slow answer."""
    result = analysed(clock, count=4, durations=[0.001, 0.3, 0.001, 0.001], errors=[1])
    assert result.values.count == 3
    assert result.values.mean == pytest.approx((0 + 2 + 3) / 3)
    assert result.response_time.count == 4
    assert result.response_time.max == pytest.approx(0.3)
    assert result.success_rate == pytest.approx(0.75)


# --- report ---

def test_report_shows_counts_and_all_sections(clock):
    """The report has a header with counts and lines for values, response time and timing."""
    report = format_report(analysed(clock, count=5))
    assert "=== stub: 5 measurements, 5 ok, 0 failed (100%) ===" in report
    for section in ("Values (A)", "Response time", "Timing", "interval between measurements"):
        assert section in report
    assert "Failures" not in report


def test_report_of_all_failed_series(clock):
    """With no successful value the report says 'no data' and shows each error reason once with its count."""
    report = format_report(analysed(clock, count=3, errors=[0, 1, 2]))
    assert "0 ok, 3 failed (0%)" in report
    assert "Values (A)     no data" in report
    assert "1x error #0" in report  # The stub gives every failure its own message


def test_report_shows_only_selected_metrics(clock):
    """Only the selected metrics appear, in the fixed report order."""
    report = format_report(analysed(clock), metrics=("mean", "max"))
    values_line = next(line for line in report.splitlines() if line.startswith("Values"))
    assert "mean" in values_line and "max" in values_line
    assert "median" not in values_line and "stdev" not in values_line


@pytest.mark.parametrize("setting, expected", [
    (None, METRICS),
    ([], METRICS),
    (["max", "mean"], ("mean", "max")),  # Report order, not config order
])
def test_report_metrics_from_config(setting, expected):
    """A missing or empty setting means all metrics; a list selects them in report order."""
    assert report_metrics_from_config({"analysis": {"statistical_metrics": setting}}) == expected


@pytest.mark.parametrize("setting, message", [
    (["mean", "meen"], "unknown metric"),
    ("mean", "must be a list"),
])
def test_invalid_report_metrics(setting, message):
    """A typo or a value that is not a list is a ConfigError."""
    with pytest.raises(ConfigError, match=message):
        report_metrics_from_config({"analysis": {"statistical_metrics": setting}})
