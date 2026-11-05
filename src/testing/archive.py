import json
import os
import platform
import re
import subprocess
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.testing.ammeter import Ammeter, Measurement
from src.testing.analysis import TestResult, analyze
from src.testing.sampling import Sample, SampleSeries, SamplingConfig
from src.utils.config import PROJECT_ROOT

# Increase when the file layout changes, so old files can still be recognised
FORMAT_VERSION = 1


class ArchiveError(Exception):
    """A run cannot be saved, found or read."""


@dataclass(frozen=True)
class RunRecord:
    """
    One archived test run: the result together with the conditions it was measured under.

    :ivar run_id: Unique ID, e.g. ``"20261105-161530-greenlee-3f9a1c2e"``: UTC start time, ammeter name and
        a random part, so IDs sort by time and two runs started in the same second do not collide.
    :ivar ammeter: Settings of the tested ammeter.
    :ivar environment: Where the run was made: Python version, operating system and code version.
    :ivar result: Measurements and their metrics.
    """
    run_id: str
    ammeter: Ammeter
    environment: Dict[str, str]
    result: TestResult

    @property
    def started_at(self) -> datetime:
        """
        :returns: When the series started, in UTC.
        """
        return datetime.fromtimestamp(self.result.series.started_at, timezone.utc)


def new_run_id(ammeter_name: str, started_at: float) -> str:
    """
    Creates a unique, readable run ID.

    :param ammeter_name: Name of the tested ammeter; characters that are unsafe in file names are replaced by ``_``.
    :param started_at: Unix time when the series started.
    :returns: ID of the form ``YYYYMMDD-HHMMSS-<ammeter>-<8 random hex digits>``, time in UTC.
    """
    time_part = datetime.fromtimestamp(started_at, timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", ammeter_name)
    return f"{time_part}-{safe_name}-{uuid.uuid4().hex[:8]}"


def current_environment() -> Dict[str, str]:
    """
    Describes where the code runs, so a result can be traced back to the code that produced it.

    :returns: Python version, operating system and git commit of the project; the commit gets ``+dirty``
        if there are uncommitted changes, and is ``"unknown"`` outside a git repository.
    """
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "code_version": _git_version(),
    }


def _git_version() -> str:
    """
    :returns: Short commit hash, with ``+dirty`` if files have uncommitted changes, or ``"unknown"``.
    """
    try:
        def git(*args: str) -> str:
            return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True,
                                  timeout=5, check=True).stdout.strip()
        commit = git("rev-parse", "--short", "HEAD")
        # New files that are not committed yet change the code as much as edited ones
        return commit + ("+dirty" if git("status", "--porcelain") else "")
    except (OSError, subprocess.SubprocessError):  # git not installed, not a repository, ...
        return "unknown"


def record_to_dict(record: RunRecord) -> Dict[str, Any]:
    """
    Converts a run to plain data for JSON. Besides the raw measurements it contains a ``summary`` with the
    metrics, so people and :meth:`ResultArchive.list` can read the results without recomputing them.

    :param record: The run.
    :returns: Dictionary with only JSON types.
    """
    result = record.result
    ammeter = asdict(record.ammeter)
    ammeter["command"] = record.ammeter.command.decode("utf-8")
    return {
        "format_version": FORMAT_VERSION,
        "run_id": record.run_id,
        "started_at": record.started_at.isoformat(),
        "ammeter": ammeter,
        "environment": record.environment,
        "summary": {
            "success_rate": result.success_rate,
            "values": asdict(result.values),
            "response_time": asdict(result.response_time),
            "timing": asdict(result.series.timing),
        },
        "series": asdict(result.series),
    }


def record_from_dict(data: Any) -> RunRecord:
    """
    Rebuilds a run from data written by :func:`record_to_dict`. The metrics are recomputed from the raw
    measurements; the stored ``summary`` is not trusted, so an edited file cannot show wrong metrics.

    :param data: Parsed JSON.
    :returns: The run, equal to the one that was saved.
    :raises ArchiveError: The data is not a run of a supported format version.
    """
    if not isinstance(data, dict) or "format_version" not in data:
        raise ArchiveError("not a run file: 'format_version' is missing")
    if data["format_version"] != FORMAT_VERSION:
        raise ArchiveError(f"format version {data['format_version']!r} is not supported (expected {FORMAT_VERSION})")
    try:
        ammeter_data = dict(data["ammeter"])
        ammeter_data["command"] = ammeter_data["command"].encode("utf-8")
        series_data = data["series"]
        series = SampleSeries(
            ammeter=series_data["ammeter"],
            config=SamplingConfig(**series_data["config"]),
            started_at=series_data["started_at"],
            samples=tuple(Sample(**{**s, "measurement": Measurement(**s["measurement"])})
                          for s in series_data["samples"]),
            schedule_shift_s=series_data["schedule_shift_s"],
        )
        if not series.samples:
            raise ArchiveError("not a valid run file: it has no measurements")
        return RunRecord(data["run_id"], Ammeter(**ammeter_data), dict(data["environment"]), analyze(series))
    except (KeyError, TypeError, ValueError, AttributeError, ZeroDivisionError) as e:
        raise ArchiveError(f"not a valid run file: {e!r}") from e


class ResultArchive:
    """
    Stores test runs as JSON files, one file per run, named ``<run_id>.json``.

    :ivar directory: Folder with the run files; created on the first save.
    """

    def __init__(self, directory: Path):
        """
        :param directory: Folder with the run files.
        """
        self.directory = Path(directory)

    def save(self, record: RunRecord) -> Path:
        """
        Saves a run. The data is written to a temporary file first and then renamed in one step, so a crash
        while writing never leaves a half-written run file behind.

        :param record: The run.
        :returns: Path of the saved file.
        :raises ArchiveError: A run with this ID already exists, or the file cannot be written.
        """
        path = self.directory / f"{record.run_id}.json"
        if path.exists():
            raise ArchiveError(f"run {record.run_id} already exists; not overwriting it")
        tmp_path = self.directory / f".{record.run_id}.json.tmp"
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                # allow_nan=False: NaN and Infinity are not valid JSON
                json.dump(record_to_dict(record), f, indent=2, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())  # Make sure the data is on disk before the rename
            # os.replace, not os.rename: os.rename fails on Windows if the target exists
            os.replace(tmp_path, path)
        except (OSError, ValueError) as e:
            raise ArchiveError(f"cannot save run {record.run_id}: {e}") from e
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
        return path

    def load(self, run_id: str) -> RunRecord:
        """
        Loads one run.

        :param run_id: Full run ID or its beginning, like a short git commit hash.
        :returns: The run.
        :raises ArchiveError: No run or more than one run matches, or the file is not a valid run.
        """
        return self._read(self._find(run_id))

    def list(self, ammeter: Optional[str] = None) -> Tuple[List[RunRecord], List[str]]:
        """
        Loads all runs, newest first. Files that cannot be read are skipped, so one broken file does not hide
        the others; they are reported in the second return value.

        :param ammeter: Only runs of this ammeter; ``None`` for all.
        :returns: The runs and one message per file that was skipped.
        """
        records, problems = [], []
        for path in self._run_files():
            try:
                record = self._read(path)
            except ArchiveError as e:
                problems.append(str(e))
                continue
            if ammeter is None or record.result.ammeter == ammeter:
                records.append(record)
        # IDs start with the UTC time, so sorting by ID sorts by time
        records.sort(key=lambda r: r.run_id, reverse=True)
        return records, problems

    def _run_files(self) -> List[Path]:
        """
        :returns: All run files; temporary ``.tmp`` files of an interrupted save are ignored.
        """
        if not self.directory.is_dir():
            return []
        return sorted(p for p in self.directory.glob("*.json") if not p.name.startswith("."))

    def _find(self, run_id: str) -> Path:
        """
        :param run_id: Full run ID or its beginning.
        :returns: Path of the only matching run file.
        :raises ArchiveError: No file or more than one file matches.
        """
        exact = self.directory / f"{run_id}.json"
        if exact.is_file():
            return exact
        matches = [p for p in self._run_files() if p.stem.startswith(run_id)]
        if not matches:
            raise ArchiveError(f"no run matches {run_id!r} in {self.directory}; use 'list' to see the runs")
        if len(matches) > 1:
            names = ", ".join(p.stem for p in matches[:5]) + (", ..." if len(matches) > 5 else "")
            raise ArchiveError(f"{run_id!r} matches {len(matches)} runs: {names}; give more characters")
        return matches[0]

    @staticmethod
    def _read(path: Path) -> RunRecord:
        """
        :param path: Path of a run file.
        :returns: The run.
        :raises ArchiveError: The file cannot be read, is not valid JSON, or is not a valid run.
        """
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:  # json.JSONDecodeError is a ValueError
            raise ArchiveError(f"{path.name}: cannot read: {e}") from e
        try:
            return record_from_dict(data)
        except ArchiveError as e:
            raise ArchiveError(f"{path.name}: {e}") from e
