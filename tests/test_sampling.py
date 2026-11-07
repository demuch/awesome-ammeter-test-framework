"""Tests of sampling: the count/duration/frequency rules and the schedule, mostly with a fake clock."""
import pytest

from src.testing.sampling import SamplingConfig, sample
from src.utils.config import DEFAULT_CONFIG_PATH, ConfigError, load_config
from tests.conftest import StubAmmeter


def run(clock, count, frequency_hz, **stub_options):
    """
    Samples a :class:`StubAmmeter` with the fake clock.

    :param clock: The fake clock.
    :param count: Number of measurements.
    :param frequency_hz: Measurements per second.
    :param stub_options: ``durations`` and ``errors`` for :class:`StubAmmeter`.
    :returns: The series.
    """
    config = SamplingConfig.from_values(count=count, frequency_hz=frequency_hz)
    return sample(StubAmmeter(clock, **stub_options), config, clock=clock.now, sleep=clock.sleep)


# --- SamplingConfig ---

@pytest.mark.parametrize("values, expected", [
    (dict(count=20, frequency_hz=10), (20, 2.0, 10.0)),
    (dict(duration_s=2, frequency_hz=10), (20, 2.0, 10.0)),
    (dict(count=20, duration_s=2), (20, 2.0, 10.0)),
    (dict(count=20, duration_s=2, frequency_hz=10), (20, 2.0, 10.0)),
    (dict(duration_s=30, frequency_hz=0.1), (3, 30.0, 0.1)),  # 30 x 0.1 is 3.0000000000000004 in floats
])
def test_any_two_values_give_the_third(values, expected):
    """Any two of count, duration and frequency define the configuration."""
    config = SamplingConfig.from_values(**values)
    assert (config.count, config.duration_s, config.frequency_hz) == pytest.approx(expected)


@pytest.mark.parametrize("values, message", [
    (dict(count=20, duration_s=1, frequency_hz=100), "contradicts"),
    (dict(count=20), "at least two"),
    (dict(), "at least two"),
    (dict(duration_s=1.5, frequency_hz=3), "not a whole number"),
    (dict(duration_s=0.01, frequency_hz=10), "not a whole number"),
    (dict(count=0, frequency_hz=10), "whole number of at least 1"),
    (dict(count=2.5, frequency_hz=10), "whole number of at least 1"),
    (dict(count=True, frequency_hz=10), "whole number of at least 1"),
    (dict(count=20, frequency_hz=-10), "greater than 0"),
    (dict(count=20, frequency_hz="10"), "greater than 0"),
    (dict(duration_s=float("inf"), frequency_hz=10), "finite number"),
    (dict(duration_s=float("nan"), frequency_hz=10), "finite number"),
])
def test_invalid_sampling_values(values, message):
    """Missing, contradicting or invalid values give a ConfigError that names the problem."""
    with pytest.raises(ConfigError, match=message):
        SamplingConfig.from_values(**values)


def test_project_config_sampling():
    """config.yaml sets 20 measurements over 2 s, so the frequency is computed as 10 Hz."""
    assert SamplingConfig.from_config(load_config(DEFAULT_CONFIG_PATH)) == SamplingConfig(20, 2.0, 10.0)


def test_missing_sampling_section():
    """A config without testing.sampling is a ConfigError."""
    with pytest.raises(ConfigError, match="testing.sampling"):
        SamplingConfig.from_config({"ammeters": {}})


# --- schedule ---

def test_measurements_start_on_schedule(clock):
    """Measurement i starts exactly at i / frequency."""
    series = run(clock, count=5, frequency_hz=10)
    assert [s.scheduled_s for s in series.samples] == pytest.approx([0.0, 0.1, 0.2, 0.3, 0.4])
    assert [s.started_s for s in series.samples] == pytest.approx([0.0, 0.1, 0.2, 0.3, 0.4])
    assert not any(s.late for s in series.samples)


def test_exact_count_and_last_moment(clock):
    """20 measurements at 10 Hz are 20, not 19 or 21, and the last one starts at 1.9 s, not 2.0 s."""
    series = run(clock, count=20, frequency_hz=10)
    assert len(series.samples) == 20
    assert series.samples[-1].scheduled_s == pytest.approx(1.9)


def test_measurement_time_is_not_added_to_the_interval(clock):
    """The wait shrinks by the time a measurement took, so delays do not add up (unlike sleep(interval))."""
    series = run(clock, count=10, frequency_hz=10, durations=[0.03] * 10)
    assert clock.sleeps == pytest.approx([0.07] * 9)
    assert series.samples[-1].started_s == pytest.approx(0.9)


def test_slow_measurement_shifts_schedule_without_burst(clock):
    """A slow reply marks the next measurements late and shifts the schedule; no catch-up burst."""
    series = run(clock, count=8, frequency_hz=10, durations=[0, 0, 0, 0.35, 0.35])
    assert [s.started_s for s in series.samples] == pytest.approx([0.0, 0.1, 0.2, 0.3, 0.65, 1.0, 1.1, 1.2])
    assert [s.index for s in series.samples if s.late] == [4, 5]
    timing = series.timing
    assert timing.schedule_shift_s == pytest.approx(0.5)
    assert timing.min_interval_s == pytest.approx(0.1)  # A burst would show up as an interval near 0
    assert timing.max_interval_s == pytest.approx(0.35)


def test_failed_measurements_stay_in_series(clock):
    """Failures do not stop the series; they are kept with their error and left out of the values."""
    series = run(clock, count=5, frequency_hz=10, errors=[1, 3])
    assert len(series.samples) == 5
    assert [s.index for s in series.failed] == [1, 3]
    assert series.values == (0.0, 2.0, 4.0)


def test_timing_stats_on_schedule(clock):
    """A series exactly on schedule has the planned frequency, no lag and no shift."""
    timing = run(clock, count=5, frequency_hz=10).timing
    assert timing.actual_frequency_hz == pytest.approx(10)
    # approx: summing 0.1 repeatedly leaves tiny float errors that are not a delay
    assert (timing.mean_lag_s, timing.max_lag_s, timing.schedule_shift_s) == pytest.approx((0, 0, 0), abs=1e-9)
    assert timing.late_count == 0


def test_timing_stats_of_one_measurement(clock):
    """With one measurement there is no frequency or interval, and nothing crashes."""
    timing = run(clock, count=1, frequency_hz=10).timing
    assert (timing.actual_frequency_hz, timing.min_interval_s, timing.max_interval_s) == (None, None, None)


@pytest.mark.integration
def test_real_time_sampling_with_emulator(emulator):
    """With the real clock, real sleep and a real emulator the series is complete and never starts early."""
    series = sample(emulator("greenlee"), SamplingConfig.from_values(count=5, frequency_hz=10))
    assert len(series.values) == 5
    # A loaded machine can only make measurements late, never early. How late is not asserted: on shared CI
    # machines it varied from 0.1 ms to over 100 ms (a frequency of 7.2 instead of 10 Hz was seen on macOS).
    # The schedule itself, late measurements and the shift are tested exactly with the fake clock above.
    assert all(s.started_s >= s.scheduled_s - 1e-6 for s in series.samples)
