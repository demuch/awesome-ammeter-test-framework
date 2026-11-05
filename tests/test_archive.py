"""Tests of the result archive: IDs, saving and loading without loss, broken files, settings."""
import json
import re
import subprocess

import pytest

from src.testing import archive as archive_module
from src.testing.ammeter import Ammeter
from src.testing.analysis import analyze
from src.testing.archive import (ArchiveError, ResultArchive, RunRecord, archive_settings_from_config,
                                 new_run_id)
from src.testing.sampling import SamplingConfig, sample
from src.utils.config import PROJECT_ROOT, ConfigError
from tests.conftest import StubAmmeter

ENVIRONMENT = {"python": "3.9.6", "platform": "test", "code_version": "abc1234"}


def make_record(clock, name="greenlee", started_at=None, **stub_options):
    """
    Creates a run of a :class:`StubAmmeter` without a network.

    :param clock: The fake clock.
    :param name: Ammeter name.
    :param started_at: Unix time to use as the start of the series (sets the time part of the ID).
    :param stub_options: ``durations`` and ``errors`` for :class:`StubAmmeter`.
    :returns: The run.
    """
    config = SamplingConfig.from_values(count=5, frequency_hz=10)
    series = sample(StubAmmeter(clock, name=name, **stub_options), config, clock=clock.now, sleep=clock.sleep)
    if started_at is not None:
        series = type(series)(series.ammeter, series.config, started_at, series.samples, series.schedule_shift_s)
    result = analyze(series)
    ammeter = Ammeter(name, 5000, b"MEASURE_GREENLEE -get_measurement", emulator="Ammeters.Greenlee_Ammeter.GreenleeAmmeter")
    return RunRecord(new_run_id(name, series.started_at), ammeter, ENVIRONMENT, result)


@pytest.fixture
def archive(tmp_path):
    """
    :returns: An empty archive in a temporary folder that pytest removes after the test.
    """
    return ResultArchive(tmp_path / "runs")


# --- run IDs ---

def test_run_id_format():
    """The ID is UTC date and time, ammeter name and 8 hex digits."""
    run_id = new_run_id("greenlee", 0)  # Unix time 0 is 1970-01-01 00:00:00 UTC, whatever the local time zone
    assert re.fullmatch(r"19700101-000000-greenlee-[0-9a-f]{8}", run_id)


def test_run_ids_are_unique_within_one_second():
    """1000 IDs for the same ammeter and second do not repeat."""
    assert len({new_run_id("greenlee", 1_700_000_000) for _ in range(1000)}) == 1000


def test_unsafe_characters_in_ammeter_name_are_replaced():
    """A name that is not safe in a file name cannot break the path."""
    assert "-lab_meter_1-" in new_run_id("lab/meter 1", 0)


# --- save and load ---

@pytest.mark.parametrize("stub_options", [
    {},
    {"errors": [0, 1, 2, 3, 4]},                    # Every measurement failed
    {"durations": [0, 0.35, 0, 0, 0]},              # Late measurements and a shifted schedule
], ids=["normal", "all-failed", "late"])
def test_loaded_run_equals_saved_run(archive, clock, stub_options):
    """Round trip: what is loaded is equal, field by field at every level, to what was saved."""
    record = make_record(clock, **stub_options)
    archive.save(record)
    assert archive.load(record.run_id) == record


def test_loaded_run_has_original_types(archive, clock):
    """JSON has no tuples or bytes; loading must restore them, otherwise == with a fresh result fails."""
    record = make_record(clock)
    archive.save(record)
    loaded = archive.load(record.run_id)
    assert type(loaded.result.series.samples) is tuple
    assert loaded.ammeter.command == b"MEASURE_GREENLEE -get_measurement"


def test_metrics_are_recomputed_not_read_from_summary(archive, clock):
    """An edited summary in the file cannot change the loaded metrics."""
    record = make_record(clock)
    path = archive.save(record)
    data = json.loads(path.read_text())
    data["summary"]["values"]["mean"] = 999.0
    path.write_text(json.dumps(data))
    assert archive.load(record.run_id).result.values.mean == record.result.values.mean


def test_existing_run_is_not_overwritten(archive, clock):
    """Saving a run with an ID that already exists is refused."""
    record = make_record(clock)
    archive.save(record)
    with pytest.raises(ArchiveError, match="already exists"):
        archive.save(record)


def test_crash_while_writing_leaves_no_file(archive, clock, monkeypatch):
    """If writing fails halfway, neither a broken run file nor a temporary file is left behind."""
    def crash_halfway(obj, f, **kwargs):
        f.write('{"run_id": "half-writ')
        raise OSError("disk full")
    monkeypatch.setattr(archive_module.json, "dump", crash_halfway)
    with pytest.raises(ArchiveError, match="disk full"):
        archive.save(make_record(clock))
    assert list(archive.directory.iterdir()) == []


# --- list and find ---

def test_list_is_newest_first_and_filters_by_ammeter(archive, clock):
    """Runs are listed newest first; --ammeter keeps only one ammeter."""
    old = make_record(clock, "greenlee", started_at=1_700_000_000)
    new = make_record(clock, "greenlee", started_at=1_700_000_100)
    other = make_record(clock, "entes", started_at=1_700_000_050)
    for record in (old, new, other):
        archive.save(record)
    records, problems = archive.list()
    assert [r.run_id for r in records] == [new.run_id, other.run_id, old.run_id]
    assert problems == []
    assert [r.run_id for r in archive.list("greenlee")[0]] == [new.run_id, old.run_id]


def test_empty_or_missing_folder_lists_nothing(tmp_path):
    """An archive folder that does not exist yet is an empty archive."""
    assert ResultArchive(tmp_path / "not-created").list() == ([], [])


@pytest.mark.parametrize("content, message", [
    ('{"format_version": 1, "run_id": "x", "ser', "cannot read"),
    ('{"hello": "world"}', "'format_version' is missing"),
    ('{"format_version": 2}', "format version 2 is not supported"),
    ('[1, 2, 3]', "'format_version' is missing"),
    ('{"format_version": 1}', "not a valid run file"),
])
def test_broken_file_is_skipped_by_list_and_rejected_by_load(archive, clock, content, message):
    """One broken file does not hide the good runs; loading it gives a clear ArchiveError."""
    good = make_record(clock)
    archive.save(good)
    (archive.directory / "broken.json").write_text(content)
    records, problems = archive.list()
    assert [r.run_id for r in records] == [good.run_id]
    assert len(problems) == 1 and message in problems[0]
    with pytest.raises(ArchiveError, match=message):
        archive.load("broken")


def test_run_without_measurements_is_rejected(archive, clock):
    """A file whose measurement list is empty is not a valid run (its report would crash)."""
    path = archive.save(make_record(clock))
    data = json.loads(path.read_text())
    data["series"]["samples"] = []
    path.write_text(json.dumps(data))
    with pytest.raises(ArchiveError, match="no measurements"):
        archive.load(path.stem)


def test_temporary_files_are_ignored(archive, clock):
    """A .tmp file left by an interrupted save is not treated as a run."""
    archive.save(make_record(clock))
    (archive.directory / ".20260101-000000-x-00000000.json.tmp").write_text("garbage")
    records, problems = archive.list()
    assert len(records) == 1 and problems == []


def test_load_by_id_beginning(archive, clock):
    """A unique beginning of the ID finds the run; an ambiguous or unknown one gives a clear error."""
    first = make_record(clock, "greenlee", started_at=1_700_000_000)
    second = make_record(clock, "entes", started_at=1_700_000_000)
    archive.save(first)
    archive.save(second)
    assert archive.load(first.run_id[:24]) == first
    with pytest.raises(ArchiveError, match="matches 2 runs"):
        archive.load(first.run_id[:15])
    with pytest.raises(ArchiveError, match="no run matches"):
        archive.load("1999")


# --- code version ---

def fake_git(outputs):
    """
    Replacement for subprocess.run that answers git commands with fixed output.

    :param outputs: Output for ``rev-parse`` and ``status``, or an exception to raise.
    :returns: Function with the signature of :func:`subprocess.run` used by the archive.
    """
    def run(args, **kwargs):
        output = outputs[args[1]]
        if isinstance(output, Exception):
            raise output
        return subprocess.CompletedProcess(args, 0, stdout=output)
    return run


@pytest.mark.parametrize("outputs, expected", [
    ({"rev-parse": "abc1234\n", "status": ""}, "abc1234"),
    ({"rev-parse": "abc1234\n", "status": " M src/testing/sampling.py\n"}, "abc1234+dirty"),
    ({"rev-parse": "abc1234\n", "status": "?? src/new_module.py\n"}, "abc1234+dirty"),
    ({"rev-parse": FileNotFoundError("git"), "status": ""}, "unknown"),
    ({"rev-parse": subprocess.CalledProcessError(128, "git"), "status": ""}, "unknown"),
    ({"rev-parse": subprocess.TimeoutExpired("git", 5), "status": ""}, "unknown"),
], ids=["clean", "edited", "new-file", "no-git", "not-a-repository", "git-hangs"])
def test_code_version(monkeypatch, outputs, expected):
    """The git commit, with +dirty for uncommitted Python changes, or 'unknown' if git cannot answer."""
    # Only _git_version() is tested: platform.platform() also calls subprocess.run on some systems
    monkeypatch.setattr(archive_module.subprocess, "run", fake_git(outputs))
    assert archive_module._git_version() == expected


def test_dirty_check_looks_only_at_python_files(monkeypatch):
    """Only *.py files are passed to git status, so saved output files do not mark the code as dirty."""
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="abc1234\n" if args[1] == "rev-parse" else "")
    monkeypatch.setattr(archive_module.subprocess, "run", run)
    archive_module._git_version()
    assert calls[1][-1] == "*.py"


# --- settings ---

def test_archive_settings_defaults():
    """Without a result_management section, runs go to results/runs in the project and are saved."""
    assert archive_settings_from_config({}) == (PROJECT_ROOT / "results" / "runs", True)


def test_absolute_results_dir_is_kept(tmp_path):
    """An absolute path is used as it is, not joined to the project root."""
    directory, _ = archive_settings_from_config({"result_management": {"results_dir": str(tmp_path)}})
    assert directory == tmp_path


@pytest.mark.parametrize("section, message", [
    ({"results_dir": ""}, "non-empty path"),
    ({"results_dir": 42}, "non-empty path"),
    ({"save_results": "yes"}, "true or false"),
    ("not a mapping", "must be a mapping"),
])
def test_invalid_archive_settings(section, message):
    """Invalid result_management values are a ConfigError."""
    with pytest.raises(ConfigError, match=message):
        archive_settings_from_config({"result_management": section})
