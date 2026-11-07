"""Tests of the precision and reliability assessment of ammeters."""
import math

import pytest

from src.results import main as results_main
from src.testing.ammeter import Measurement
from src.testing.archive import ResultArchive
from src.testing.assessment import assess, format_assessment, t_critical
from src.testing.sampling import Sample, SampleSeries, SamplingConfig
from src.testing.analysis import analyze
from tests.test_archive import make_record


def record_with_values(clock, name, values, durations=None, started_at=1_700_000_000):
    """
    Builds a run of ``name`` whose successful values are exactly ``values`` (``None`` = failed measurement).

    :param clock: The fake clock, used by :func:`make_record` for the metadata.
    :param name: Ammeter name.
    :param values: Value of each measurement in order.
    :param durations: Response time of each measurement in seconds; by default 1, 2, 3 ... ms.
    :param started_at: Unix time of the run.
    :returns: The run.
    """
    durations = durations or [0.001 * (i + 1) for i in range(len(values))]
    samples = tuple(Sample(i, i * 0.1, i * 0.1, False,
                           Measurement(name, 0.0, v, None if v is not None else "failed", d))
                    for i, (v, d) in enumerate(zip(values, durations)))
    series = SampleSeries(name, SamplingConfig.from_values(count=len(values), frequency_hz=10), started_at, samples, 0.0)
    base = make_record(clock, name, started_at=started_at)
    return type(base)(base.run_id, base.ammeter, base.environment, analyze(series))


# --- t quantile ---

@pytest.mark.parametrize("df, expected", [(1, 12.706), (4, 2.776), (19, 2.093), (30, 2.042),
                                          (40, 2.021), (60, 2.000), (120, 1.980), (1000, 1.962)])
def test_t_critical_matches_statistical_tables(df, expected):
    """The multiplier equals the table value: exact up to 30, within 0.0005 above (approximation)."""
    assert t_critical(df) == pytest.approx(expected, abs=0.0005)


def test_t_critical_needs_at_least_one_degree_of_freedom():
    """One value has no spread, so there is no interval."""
    with pytest.raises(ValueError):
        t_critical(0)


# --- interval and pooling ---

def test_confidence_interval_of_known_data(clock):
    """10, 11, 9, 10, 60: mean 20, stdev sqrt(2002/4); half-width = 2.776 x stdev / sqrt(5), worked out by hand."""
    (a,) = assess([record_with_values(clock, "x", [10, 11, 9, 10, 60])])
    half_width = 2.776 * math.sqrt(2002 / 4) / math.sqrt(5)
    assert (a.ci_low, a.ci_high) == pytest.approx((20 - half_width, 20 + half_width))
    assert a.ci_relative_half_width == pytest.approx(half_width / 20)


def test_runs_of_one_ammeter_are_pooled(clock):
    """Two runs of one ammeter become one assessment with all measurements, and its interval is narrower."""
    one = assess([record_with_values(clock, "g", [1, 2, 3, 4])])[0]
    both = assess([record_with_values(clock, "g", [1, 2, 3, 4]),
                   record_with_values(clock, "g", [1, 2, 3, 4], started_at=1_700_000_100)])[0]
    assert (both.runs, both.measurements, both.values.count) == (2, 8, 8)
    assert both.ci_relative_half_width < one.ci_relative_half_width


def test_fewer_than_two_values_have_no_interval(clock):
    """With one successful value there is a mean but no interval; with none, no mean either."""
    single = assess([record_with_values(clock, "a", [5, None, None])])[0]
    none = assess([record_with_values(clock, "b", [None, None])])[0]
    assert single.values.mean == 5 and single.ci_low is None and single.ci_relative_half_width is None
    assert none.values.mean is None and none.ci_low is None


# --- ranking ---

def test_success_rate_ranks_first(clock):
    """An ammeter that fails some requests ranks below one that answers all, however steady its values are."""
    answers_all = record_with_values(clock, "answers_all", [1, 20, 5, 15, 9])
    failing = record_with_values(clock, "failing", [10, 10, 10, None, 10])  # Perfectly steady values, but 20% failed
    assert [a.ammeter for a in assess([failing, answers_all])] == ["answers_all", "failing"]


def test_spread_of_values_does_not_change_the_rank(clock):
    """The spread of values is shown but not ranked: with random emulator inputs it says nothing about the ammeter."""
    timing = [0.001, 0.002, 0.001, 0.002, 0.001]
    steady_values = record_with_values(clock, "steady_values", [10, 10.1, 9.9, 10, 10], durations=timing)
    noisy_values = record_with_values(clock, "noisy_values", [1, 20, 5, 15, 9], durations=[0.001] * 5)
    # noisy_values answers more evenly, so it ranks first although its values spread far more
    assert [a.ammeter for a in assess([steady_values, noisy_values])] == ["noisy_values", "steady_values"]


def test_response_time_spread_breaks_ties(clock):
    """With equal success rate and value spread, the steadier response time ranks higher."""
    steady = record_with_values(clock, "steady", [1, 2, 3], durations=[0.001, 0.001, 0.001])
    uneven = record_with_values(clock, "uneven", [1, 2, 3], durations=[0.001, 0.5, 0.001])
    assert [a.ammeter for a in assess([uneven, steady])] == ["steady", "uneven"]


# --- report and command ---

def test_report_names_the_best_and_states_what_it_does_not_measure(clock):
    """The report names the most reliable ammeter, the ranking rule and that accuracy is not assessed."""
    text = format_assessment(assess([record_with_values(clock, "a", [1, 1.1, 0.9], durations=[0.001] * 3),
                                     record_with_values(clock, "b", [1, 5, 9], durations=[0.001, 0.5, 0.001])]), 2)
    assert "Most dependable to query: a" in text
    assert "Most reliable" not in text
    assert "not ranked" in " ".join(text.split())
    assert "not accuracy" in " ".join(text.split())  # The note is wrapped over several lines
    assert all(len(line) <= 110 for line in text.splitlines())


def test_assess_command(tmp_path, clock, capsys):
    """'assess' prints the table for the given runs; an unknown run is an error with exit code 1."""
    archive = ResultArchive(tmp_path)
    first, second = make_record(clock, "greenlee", started_at=1_700_000_000), make_record(clock, "entes", started_at=1_700_000_100)
    archive.save(first)
    archive.save(second)
    assert results_main(["--dir", str(tmp_path), "assess", first.run_id, second.run_id]) == 0
    out = capsys.readouterr().out
    assert "Assessment of 2 ammeter(s) from 2 run(s)" in out and "95% CI OF MEAN" in out
    assert results_main(["--dir", str(tmp_path), "assess", "1999"]) == 1
