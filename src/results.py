"""
View and compare archived test runs.

Usage (from the project root)::

    python -m src.results list [--ammeter NAME]
    python -m src.results show RUN_ID
    python -m src.results compare RUN_ID RUN_ID [RUN_ID ...]
    python -m src.results --dir sample_results list

A RUN_ID may be shortened to any unique beginning, like a git commit hash.
"""
import argparse
import sys
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from src.testing.analysis import format_report
from src.testing.archive import ArchiveError, ResultArchive, RunRecord, archive_settings_from_config
from src.utils.config import DEFAULT_CONFIG_PATH, ConfigError, load_config

# Rows of the compare table: label, how to get the value from a run, how to show and compare it
_COMPARE_ROWS: Sequence[Tuple[str, Callable[[RunRecord], Optional[float]], str]] = (
    ("mean", lambda r: r.result.values.mean, "value"),
    ("median", lambda r: r.result.values.median, "value"),
    ("stdev", lambda r: r.result.values.stdev, "value"),
    ("min", lambda r: r.result.values.min, "value"),
    ("max", lambda r: r.result.values.max, "value"),
    ("relative_spread", lambda r: r.result.values.relative_spread, "share"),
    ("success rate", lambda r: r.result.success_rate, "share"),
    ("actual frequency", lambda r: r.result.series.timing.actual_frequency_hz, "hz"),
    ("response time mean", lambda r: r.result.response_time.mean, "ms"),
    ("response time max", lambda r: r.result.response_time.max, "ms"),
    ("late measurements", lambda r: r.result.series.timing.late_count, "count"),
)


def main(argv: Optional[List[str]] = None) -> int:
    """
    Runs one command.

    :param argv: Command-line arguments without the program name; by default ``sys.argv[1:]``.
    :returns: Exit code: 0 on success, 1 if a run or the archive cannot be read.
    """
    parser = argparse.ArgumentParser(prog="python -m src.results", description="View and compare archived test runs.")
    parser.add_argument("--dir", type=Path,
                        help="archive folder (default: result_management.results_dir in config.yaml)")
    commands = parser.add_subparsers(dest="command", required=True, metavar="{list,show,compare}")
    list_parser = commands.add_parser("list", help="list saved runs, newest first")
    list_parser.add_argument("--ammeter", help="only runs of this ammeter")
    show_parser = commands.add_parser("show", help="show the full report of one run")
    show_parser.add_argument("run_id", help="run ID or its unique beginning")
    compare_parser = commands.add_parser("compare", help="compare metrics of several runs side by side")
    compare_parser.add_argument("run_ids", nargs="+", metavar="run_id", help="two or more run IDs or their beginnings")
    args = parser.parse_args(argv)
    if args.command == "compare" and len(args.run_ids) < 2:
        compare_parser.error("give at least two runs to compare")

    try:
        # A mistyped --dir must not look like an empty archive; the default folder may not exist before the first run
        if args.dir is not None and not args.dir.is_dir():
            raise ArchiveError(f"folder {args.dir} does not exist")
        directory = args.dir or archive_settings_from_config(load_config(DEFAULT_CONFIG_PATH))[0]
        archive = ResultArchive(directory)
        if args.command == "list":
            _list(archive, args.ammeter)
        elif args.command == "show":
            print(_show(archive.load(args.run_id)))
        else:
            print(_compare([archive.load(run_id) for run_id in args.run_ids]))
    except (ArchiveError, ConfigError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def _list(archive: ResultArchive, ammeter: Optional[str]) -> None:
    """
    Prints one line per run and a warning per file that could not be read.

    :param archive: Archive to list.
    :param ammeter: Only runs of this ammeter; ``None`` for all.
    """
    records, problems = archive.list(ammeter)
    for problem in problems:
        print(f"Warning: skipped {problem}", file=sys.stderr)
    if not records:
        print(f"No runs in {archive.directory}" + (f" for ammeter {ammeter!r}" if ammeter else ""))
        return
    # Column widths follow the longest ID and ammeter name, so long names do not run into the next column
    id_width = max(len(r.run_id) for r in records) + 2
    name_width = max(len("AMMETER"), *(len(r.result.ammeter) for r in records)) + 2
    print(f"{'RUN ID':<{id_width}}{'AMMETER':<{name_width}}{'MEASUREMENTS':>12}{'OK':>6}{'MEAN':>11}{'STDEV':>11}")
    for r in records:
        values = r.result.values
        print(f"{r.run_id:<{id_width}}{r.result.ammeter:<{name_width}}{len(r.result.series.samples):>12}"
              f"{r.result.success_rate:>6.0%}{_format(values.mean, 'value'):>11}{_format(values.stdev, 'value'):>11}")


def _show(record: RunRecord) -> str:
    """
    :param record: Run to show.
    :returns: Metadata of the run followed by its full report.
    """
    a, config, env = record.ammeter, record.result.series.config, record.environment
    lines = [
        f"Run        {record.run_id}",
        f"Started    {record.started_at:%Y-%m-%d %H:%M:%S} UTC",
        f"Ammeter    {a.name} at {a.host}:{a.port}, command {a.command.decode('utf-8')!r}"
        + (f", emulator {a.emulator}" if a.emulator else ", real device"),
        f"Sampling   {config.count} measurements over {config.duration_s:g} s at {config.frequency_hz:g} Hz",
        f"Python     {env.get('python', 'unknown')} on {env.get('platform', 'unknown')}",
        f"Code       {env.get('code_version', 'unknown')}",
        "",
        format_report(record.result),
    ]
    return "\n".join(lines)


def _compare(records: List[RunRecord]) -> str:
    """
    :param records: Two or more runs; the change column compares the last one with the first one.
    :returns: A legend of the runs and a table of their metrics.
    """
    lines = [f"#{i}  {r.run_id}  {r.started_at:%Y-%m-%d %H:%M:%S} UTC" for i, r in enumerate(records, 1)]
    if len({r.result.ammeter for r in records}) > 1:
        lines.append("Note: the runs are from different ammeters, whose values have different scales; "
                     "compare relative_spread rather than absolute values.")
    last = len(records)
    lines.append("")
    lines.append(f"{'METRIC':<20}" + "".join(f"{'#' + str(i):>12}" for i in range(1, last + 1))
                 + f"   CHANGE (#{last} vs #1)")
    for label, get, kind in _COMPARE_ROWS:
        values = [get(r) for r in records]
        lines.append(f"{label:<20}" + "".join(f"{_format(v, kind):>12}" for v in values)
                     + f"   {_change(values[0], values[-1], kind)}")
    return "\n".join(lines)


def _format(value: Optional[float], kind: str) -> str:
    """
    :param value: Value to show, or ``None``.
    :param kind: ``"value"``, ``"share"`` (shown in percent), ``"hz"``, ``"ms"`` (value in seconds) or ``"count"``.
    :returns: The value as text, ``"n/a"`` for ``None``.
    """
    if value is None:
        return "n/a"
    if kind == "share":
        return f"{value:.1%}"
    if kind == "hz":
        return f"{value:.2f} Hz"
    if kind == "ms":
        return f"{value * 1000:.2f} ms"
    if kind == "count":
        return str(value)
    return f"{value:.4g}"


def _change(first: Optional[float], last: Optional[float], kind: str) -> str:
    """
    Describes how a metric changed. Shares change in percentage points (95% -> 100% is +5.0 pp), because
    "+5%" would be ambiguous; counts change by a number; everything else by percent of the first value.

    :param first: Value of the first run.
    :param last: Value of the last run.
    :param kind: Kind of the metric, see :func:`_format`.
    :returns: The change as text, ``"n/a"`` if it cannot be computed.
    """
    if first is None or last is None:
        return "n/a"
    if kind == "share":
        return f"{(last - first) * 100:+.1f} pp"
    if kind == "count":
        return f"{last - first:+d}"
    if first == 0:
        return "n/a"
    return f"{(last - first) / abs(first):+.1%}"


if __name__ == "__main__":
    sys.exit(main())
