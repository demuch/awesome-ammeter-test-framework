"""
Precision and reliability of ammeters from archived runs.

This does not measure accuracy (closeness to the true current): that needs a known reference current, or ammeters
measuring the same source at the same time. It measures how consistent each ammeter is and how precisely the mean
of its values is known.
"""
import math
import statistics
import textwrap
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from src.testing.analysis import ValueStats
from src.testing.archive import RunRecord

CONFIDENCE = 0.95

# Two-sided 95% critical values of Student's t for 1-30 degrees of freedom (standard statistical tables)
_T_TABLE = (12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
            2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
            2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042)

CAVEAT = ("This compares consistency and how precisely each mean is known, not accuracy: accuracy needs a known "
          "reference current, or ammeters measuring the same source at the same time. The emulators return "
          "independent random values, so their means cannot be compared with each other.")
RANKING_RULE = ("Ranked by success rate (higher first), then relative spread of values, then relative spread of "
                "response times (lower first).")


def t_critical(degrees_of_freedom: int) -> float:
    """
    Multiplier of the standard error for a two-sided 95% confidence interval of a mean.

    :param degrees_of_freedom: Number of values minus 1; at least 1.
    :returns: Student's t quantile: from the table up to 30, above that from the Cornish-Fisher expansion around the
        normal quantile (within 0.0003 of the table values). scipy would give the same, but is a large dependency.
    """
    if degrees_of_freedom < 1:
        raise ValueError(f"degrees of freedom must be at least 1, got {degrees_of_freedom}")
    if degrees_of_freedom <= len(_T_TABLE):
        return _T_TABLE[degrees_of_freedom - 1]
    z = statistics.NormalDist().inv_cdf(1 - (1 - CONFIDENCE) / 2)
    df = degrees_of_freedom
    return (z + (z ** 3 + z) / (4 * df) + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * df ** 2)
            + (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / (384 * df ** 3))


@dataclass(frozen=True)
class AmmeterAssessment:
    """
    Pooled measurements of all given runs of one ammeter.

    :ivar ammeter: Ammeter name.
    :ivar runs: Number of runs pooled.
    :ivar measurements: Number of measurements in those runs, successful or not.
    :ivar success_rate: Share of successful measurements, from 0.0 to 1.0.
    :ivar values: Metrics of all successful values.
    :ivar response_time: Metrics of all response times, in seconds.
    :ivar ci_low: Lower end of the 95% confidence interval of the mean, or ``None`` for fewer than two values.
    :ivar ci_high: Upper end of the 95% confidence interval of the mean, or ``None`` for fewer than two values.
    """
    ammeter: str
    runs: int
    measurements: int
    success_rate: float
    values: ValueStats
    response_time: ValueStats
    ci_low: Optional[float]
    ci_high: Optional[float]

    @property
    def ci_relative_half_width(self) -> Optional[float]:
        """
        :returns: Half the confidence interval relative to the mean ("the mean is known to within +-X%"), or
            ``None`` if there is no interval or the mean is 0.
        """
        if self.ci_low is None or not self.values.mean:
            return None
        return (self.ci_high - self.ci_low) / 2 / abs(self.values.mean)


def assess(records: Sequence[RunRecord]) -> List[AmmeterAssessment]:
    """
    Pools the runs of each ammeter and ranks the ammeters by reliability.

    :param records: Runs of one or more ammeters; several runs of one ammeter are pooled, which narrows the interval.
    :returns: One assessment per ammeter, most reliable first (see :data:`RANKING_RULE`).
    """
    grouped: Dict[str, List[RunRecord]] = {}
    for record in records:
        grouped.setdefault(record.result.ammeter, []).append(record)

    assessments = []
    for ammeter, runs in grouped.items():
        samples = [s for run in runs for s in run.result.series.samples]
        values = [s.measurement.value for s in samples if s.measurement.ok]
        stats = ValueStats.from_values(values)
        ci_low = ci_high = None
        if stats.stdev is not None:
            half_width = t_critical(stats.count - 1) * stats.stdev / math.sqrt(stats.count)
            ci_low, ci_high = stats.mean - half_width, stats.mean + half_width
        assessments.append(AmmeterAssessment(
            ammeter, len(runs), len(samples), len(values) / len(samples), stats,
            ValueStats.from_values([s.measurement.duration_s for s in samples]), ci_low, ci_high))
    return sorted(assessments, key=_rank_key)


def _rank_key(a: AmmeterAssessment) -> Tuple[float, float, float]:
    """
    :param a: One assessment.
    :returns: Sort key of :data:`RANKING_RULE`; a missing spread counts as worst.
    """
    return (-a.success_rate,
            a.values.relative_spread if a.values.relative_spread is not None else math.inf,
            a.response_time.relative_spread if a.response_time.relative_spread is not None else math.inf)


def format_assessment(assessments: Sequence[AmmeterAssessment], run_count: int) -> str:
    """
    :param assessments: Result of :func:`assess`.
    :param run_count: Number of runs that were assessed.
    :returns: A table with the rank of each ammeter, followed by how it was ranked and what it does not measure.
    """
    lines = [f"Assessment of {len(assessments)} ammeter(s) from {run_count} run(s)", "",
             f"{'RANK':<5}{'AMMETER':<12}{'RUNS':>5}{'MEASURED':>9}{'OK':>6}{'MEAN':>10}"
             f"{'95% CI OF MEAN':>24}{'+-':>7}{'SPREAD':>8}{'RESPONSE SPREAD':>17}"]
    for rank, a in enumerate(assessments, 1):
        interval = "n/a" if a.ci_low is None else f"{_number(a.ci_low)} .. {_number(a.ci_high)}"
        lines.append(f"{rank:<5}{a.ammeter:<12}{a.runs:>5}{a.measurements:>9}{a.success_rate:>6.0%}"
                     f"{_number(a.values.mean):>10}{interval:>24}{_share(a.ci_relative_half_width):>7}"
                     f"{_share(a.values.relative_spread):>8}{_share(a.response_time.relative_spread):>17}")
    lines.append("")
    if len(assessments) > 1:
        best = assessments[0]
        lines.append(f"Most reliable: {best.ammeter} ({best.success_rate:.0%} successful, "
                     f"relative spread {_share(best.values.relative_spread)}).")
    notes = (RANKING_RULE,
             "95% CI: the range that contains the ammeter's true mean with 95% confidence; +- is its half-width "
             "relative to the mean. More measurements narrow it.",
             CAVEAT)
    lines += [textwrap.fill(note, width=100) for note in notes]  # Readable in a narrow terminal
    return "\n".join(lines)


def _number(value: Optional[float]) -> str:
    """
    :param value: A value or ``None``.
    :returns: The value with 4 significant digits, or ``"n/a"``.
    """
    return "n/a" if value is None else f"{value:.4g}"


def _share(value: Optional[float]) -> str:
    """
    :param value: A share (0.25 = 25%) or ``None``.
    :returns: The share in whole percent, or ``"n/a"``.
    """
    return "n/a" if value is None else f"{value:.0%}"
