"""Tests of plots: files are written, settings are read, and a missing matplotlib gives a clear message."""
import sys

import pytest
import yaml

from src.results import main as results_main
from src.run import main as run_main
from src.testing.archive import ResultArchive
from src.testing.plots import PLOT_TYPES, PlotError, plot_comparison, plot_run, plot_types_from_config
from src.utils import logger as logger_module
from src.utils.config import ConfigError
from tests.conftest import EMULATORS, free_port
from tests.test_archive import make_record

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def no_matplotlib(monkeypatch):
    """
    Makes ``import matplotlib`` fail, as on a machine without requirements-plot.txt.
    """
    monkeypatch.setitem(sys.modules, "matplotlib", None)  # None in sys.modules makes the import raise ImportError


def is_png(path) -> bool:
    """
    :param path: File to check.
    :returns: ``True`` if the file exists and starts like a PNG image.
    """
    return path.is_file() and path.read_bytes()[:8] == PNG_SIGNATURE


# --- drawing ---

@pytest.mark.parametrize("stub_options, theme", [
    ({}, "light"),
    ({}, "dark"),
    ({"errors": [1, 3]}, "light"),               # Failed measurements are marked
    ({"errors": [0, 1, 2, 3, 4]}, "light"),      # No value at all: nothing to put in the histogram
    ({"durations": [0, 0.35, 0, 0, 0]}, "dark"),  # Late measurements are marked
], ids=["normal", "dark", "some-failed", "all-failed", "late"])
def test_plot_run_writes_png(tmp_path, clock, stub_options, theme):
    """A run is drawn to a PNG file in both themes, also with failed or late measurements."""
    pytest.importorskip("matplotlib")
    path = plot_run(make_record(clock, **stub_options), tmp_path / "plots" / "run.png", theme=theme)
    assert is_png(path)


def test_plot_run_with_selected_panels(tmp_path, clock):
    """Only the selected panels can be drawn."""
    pytest.importorskip("matplotlib")
    assert is_png(plot_run(make_record(clock), tmp_path / "run.png", ("values", "timing")))


def test_plot_comparison_writes_png(tmp_path, clock):
    """Several runs, also of different ammeters, are compared in one PNG."""
    pytest.importorskip("matplotlib")
    records = [make_record(clock, "greenlee"), make_record(clock, "entes"), make_record(clock, "greenlee", errors=[2])]
    assert is_png(plot_comparison(records, tmp_path / "compare.png"))


def test_comparison_of_runs_without_values_is_an_error(tmp_path, clock):
    """Runs where every measurement failed have no values to compare."""
    pytest.importorskip("matplotlib")
    records = [make_record(clock, errors=[0, 1, 2, 3, 4]), make_record(clock, errors=[0, 1, 2, 3, 4])]
    with pytest.raises(PlotError, match="no.*successful measurements"):
        plot_comparison(records, tmp_path / "compare.png")


def test_unwritable_file_is_a_plot_error(tmp_path, clock):
    """A file that cannot be written is a PlotError with the path, not an OSError with a traceback."""
    pytest.importorskip("matplotlib")
    (tmp_path / "a_file").write_text("")  # A file where the folder of the plot should be
    with pytest.raises(PlotError, match="cannot write plot"):
        plot_run(make_record(clock), tmp_path / "a_file" / "run.png")


def test_missing_matplotlib_gives_install_hint(tmp_path, clock, no_matplotlib):
    """Without matplotlib the error says what to install; the rest of the framework does not need it."""
    with pytest.raises(PlotError, match="pip install -r requirements-plot.txt"):
        plot_run(make_record(clock), tmp_path / "run.png")


# --- settings ---

@pytest.mark.parametrize("section, expected", [
    (None, (True, PLOT_TYPES)),
    ({"enabled": False}, (False, PLOT_TYPES)),
    ({"enabled": True, "plot_types": []}, (True, PLOT_TYPES)),
    ({"plot_types": ["timing", "values"]}, (True, ("values", "timing"))),  # Figure order, not config order
])
def test_plot_settings(section, expected):
    """Plots are on by default with every panel; plot_types selects panels in figure order."""
    assert plot_types_from_config({"analysis": {"visualization": section}}) == expected


@pytest.mark.parametrize("section, message", [
    ({"enabled": "yes"}, "true or false"),
    ({"plot_types": "values"}, "must be a list"),
    ({"plot_types": ["values", "pie"]}, "unknown plot"),
])
def test_invalid_plot_settings(section, message):
    """Invalid visualization settings are a ConfigError."""
    with pytest.raises(ConfigError, match=message):
        plot_types_from_config({"analysis": {"visualization": section}})


# --- command line ---

def test_results_plot_command(tmp_path, clock, capsys):
    """'plot' with one run writes it next to the run; with several runs it writes a comparison."""
    pytest.importorskip("matplotlib")
    archive = ResultArchive(tmp_path)
    first = make_record(clock, "greenlee", started_at=1_700_000_000)
    second = make_record(clock, "entes", started_at=1_700_000_100)
    archive.save(first)
    archive.save(second)
    assert results_main(["--dir", str(tmp_path), "plot", first.run_id[:24]]) == 0
    assert is_png(tmp_path / f"{first.run_id}.png")
    assert results_main(["--dir", str(tmp_path), "plot", first.run_id, second.run_id, "--theme", "dark"]) == 0
    assert is_png(tmp_path / f"compare_{first.run_id}_{second.run_id}.png")
    assert "Saved plot to" in capsys.readouterr().out


def test_results_plot_without_matplotlib_exits_with_1(tmp_path, clock, capsys, no_matplotlib):
    """Without matplotlib the plot command fails with the install hint and exit code 1."""
    record = make_record(clock)
    ResultArchive(tmp_path).save(record)
    assert results_main(["--dir", str(tmp_path), "plot", record.run_id]) == 1
    assert "requirements-plot.txt" in capsys.readouterr().err


def test_results_plot_to_unwritable_file_exits_with_1(tmp_path, clock, capsys):
    """The plot command reports a file it cannot write and exits with 1, without a traceback."""
    pytest.importorskip("matplotlib")
    record = make_record(clock)
    ResultArchive(tmp_path).save(record)
    (tmp_path / "a_file").write_text("")
    assert results_main(["--dir", str(tmp_path), "plot", record.run_id, "--output", str(tmp_path / "a_file" / "p.png")]) == 1
    err = capsys.readouterr().err
    assert "cannot write plot" in err and "Traceback" not in err


@pytest.fixture
def run_config(tmp_path, monkeypatch):
    """
    Writes a config with one Greenlee emulator on a free port and an archive in a temporary folder.

    :returns: A function that takes ``enabled`` for analysis.visualization and returns the config path.
    """
    monkeypatch.setattr(logger_module, "PROJECT_ROOT", tmp_path)
    class_path, command = EMULATORS["greenlee"]

    def write(enabled: bool):
        """
        :param enabled: Value of analysis.visualization.enabled.
        :returns: Path of the config file.
        """
        data = {"testing": {"sampling": {"measurements_count": 3, "sampling_frequency_hz": 50}},
                "ammeters": {"greenlee": {"port": free_port(), "command": command.decode(), "emulator": class_path}},
                "analysis": {"visualization": {"enabled": enabled}},
                "result_management": {"results_dir": str(tmp_path / "runs")}}
        path = tmp_path / f"config_{enabled}.yaml"
        path.write_text(yaml.safe_dump(data, sort_keys=False))
        return path
    return write


@pytest.mark.integration
@pytest.mark.parametrize("enabled, plots", [(True, 1), (False, 0)])
def test_run_saves_a_plot_of_every_archived_run(tmp_path, run_config, enabled, plots):
    """With visualization enabled, python -m src.run writes a plot next to each archived run."""
    pytest.importorskip("matplotlib")
    assert run_main(["--config", str(run_config(enabled))]) == 0
    assert len(list((tmp_path / "runs").glob("*.png"))) == plots
    assert len(list((tmp_path / "runs").glob("*.json"))) == 1


@pytest.mark.integration
def test_run_without_matplotlib_skips_plots_but_completes(tmp_path, run_config, capsys, no_matplotlib):
    """Plots are optional: without matplotlib the run still archives its result and exits with 0."""
    assert run_main(["--config", str(run_config(True))]) == 0
    assert "Plots skipped" in capsys.readouterr().err
    assert len(list((tmp_path / "runs").glob("*.json"))) == 1
    assert list((tmp_path / "runs").glob("*.png")) == []


@pytest.mark.integration
def test_run_keeps_the_archived_run_when_its_plot_cannot_be_written(tmp_path, run_config, capsys, monkeypatch):
    """A plot that cannot be written is a warning: the run is archived and the exit code stays 0."""
    def failing_plot(*args, **kwargs):
        raise PlotError("cannot write plot x.png: disk full")
    monkeypatch.setattr("src.run.plot_run", failing_plot)
    assert run_main(["--config", str(run_config(True))]) == 0
    assert "[WARNING]" in capsys.readouterr().err
    assert len(list((tmp_path / "runs").glob("*.json"))) == 1
