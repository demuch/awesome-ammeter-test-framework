"""Tests of the archive commands: python -m src.results list / show / compare."""
import pytest

from src.results import main
from src.testing.archive import ResultArchive
from tests.test_archive import make_record


@pytest.fixture
def runs(tmp_path, clock):
    """
    Archive with three runs: two of greenlee (one with a failed measurement) and one of entes.

    :returns: The archive folder and the three runs, oldest first.
    """
    archive = ResultArchive(tmp_path / "runs")
    records = [
        make_record(clock, "greenlee", started_at=1_700_000_000),
        make_record(clock, "greenlee", started_at=1_700_000_100, errors=[2]),
        make_record(clock, "entes", started_at=1_700_000_200),
    ]
    for record in records:
        archive.save(record)
    return archive.directory, records


def run_cli(directory, *args):
    """
    :param directory: Archive folder passed with --dir.
    :param args: Command and its arguments.
    :returns: Exit code of the command.
    """
    return main(["--dir", str(directory), *args])


def test_list_shows_all_runs_newest_first(runs, capsys):
    """list prints one line per run, newest first, with the success rate."""
    directory, records = runs
    assert run_cli(directory, "list") == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("RUN ID")
    assert [line.split()[0] for line in lines[1:]] == [r.run_id for r in reversed(records)]
    assert "80%" in lines[2]  # The greenlee run with one failed measurement out of 5


def test_list_filters_by_ammeter(runs, capsys):
    """--ammeter keeps only the runs of one ammeter."""
    directory, _ = runs
    run_cli(directory, "list", "--ammeter", "entes")
    rows = capsys.readouterr().out.splitlines()[1:]
    assert len(rows) == 1 and "entes" in rows[0]


def test_show_prints_metadata_and_report(runs, capsys):
    """show accepts a shortened ID and prints the metadata and the full report."""
    directory, records = runs
    assert run_cli(directory, "show", records[0].run_id[:24]) == 0
    out = capsys.readouterr().out
    assert f"Run        {records[0].run_id}" in out
    assert "Code       abc1234" in out
    assert "=== greenlee: 5 measurements, 5 ok, 0 failed (100%) ===" in out


def test_compare_shows_change_in_percent_and_percentage_points(runs, capsys):
    """compare prints both runs and the change; the success rate changes in percentage points."""
    directory, records = runs
    assert run_cli(directory, "compare", records[0].run_id, records[1].run_id) == 0
    out = capsys.readouterr().out
    assert "CHANGE (#2 vs #1)" in out
    success_line = next(line for line in out.splitlines() if line.startswith("success rate"))
    assert success_line.split()[-2:] == ["-20.0", "pp"]
    assert "different ammeters" not in out


def test_compare_warns_about_different_ammeters(runs, capsys):
    """Comparing runs of different ammeters prints a warning about the different scales."""
    directory, records = runs
    run_cli(directory, "compare", records[0].run_id, records[2].run_id)
    assert "different ammeters" in capsys.readouterr().out


@pytest.mark.parametrize("args, message", [
    (["show", "1999"], "no run matches"),
    (["show", "2023"], "matches 3 runs"),
])
def test_unknown_or_ambiguous_id_exits_with_1(runs, capsys, args, message):
    """An ID that matches no run or several runs is an error with exit code 1."""
    directory, _ = runs
    assert run_cli(directory, *args) == 1
    assert message in capsys.readouterr().err


def test_missing_dir_exits_with_1(tmp_path, capsys):
    """A mistyped --dir is an error, not an empty archive."""
    assert main(["--dir", str(tmp_path / "typo"), "list"]) == 1
    assert "does not exist" in capsys.readouterr().err


@pytest.mark.parametrize("args", [["compare", "only-one"], ["show"], ["unknown-command"]])
def test_usage_errors_exit_with_2(runs, args):
    """Wrong command-line usage exits with code 2, as argparse does."""
    directory, _ = runs
    with pytest.raises(SystemExit) as exit_info:
        run_cli(directory, *args)
    assert exit_info.value.code == 2
