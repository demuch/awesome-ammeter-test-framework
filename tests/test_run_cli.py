"""Tests of the test runner command: python -m src.run."""
import socket

import pytest
import yaml

from src.run import main
from src.utils import logger as logger_module
from tests.conftest import EMULATORS, free_port

pytestmark = pytest.mark.integration


@pytest.fixture
def config(tmp_path, monkeypatch):
    """
    Writes a config with all three emulators on free ports, short sampling and an archive in a temporary folder;
    log files go to the temporary folder too.

    :returns: Path of the config file and of the archive folder.
    """
    monkeypatch.setattr(logger_module, "PROJECT_ROOT", tmp_path)
    runs = tmp_path / "runs"
    data = {
        "testing": {"sampling": {"measurements_count": 3, "sampling_frequency_hz": 50}},
        "ammeters": {name: {"port": free_port(), "command": command.decode(), "emulator": class_path}
                     for name, (class_path, command) in EMULATORS.items()},
        "result_management": {"results_dir": str(runs)},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path, runs


def test_runs_every_ammeter_archives_and_reports(config, capsys):
    """Without options every configured ammeter is tested, archived and reported."""
    path, runs = config
    assert main(["--config", str(path)]) == 0
    out = capsys.readouterr().out
    for name in EMULATORS:
        assert f"=== {name}: 3 measurements, 3 ok" in out
    assert len(list(runs.glob("*.json"))) == 3


@pytest.mark.parametrize("options", [
    ["--ammeter", "entes", "circutor"],
    ["--ammeter", "entes", "--ammeter", "circutor"],
], ids=["one-option", "repeated-option"])
def test_only_selected_ammeters(config, capsys, options):
    """--ammeter limits the run to the named ammeters, given after one option or by repeating it."""
    path, runs = config
    assert main(["--config", str(path), *options]) == 0
    out = capsys.readouterr().out
    assert "Results for entes" in out and "Results for circutor" in out and "greenlee" not in out
    assert len(list(runs.glob("*.json"))) == 2


def test_sampling_options_replace_config(config, capsys):
    """Two sampling options replace the configured sampling for this run."""
    path, _ = config
    assert main(["--config", str(path), "--ammeter", "greenlee", "--count", "4", "--frequency", "100"]) == 0
    assert "=== greenlee: 4 measurements" in capsys.readouterr().out


def test_no_save_writes_nothing(config):
    """--no-save keeps the archive empty even though saving is on in the config."""
    path, runs = config
    assert main(["--config", str(path), "--ammeter", "greenlee", "--no-save"]) == 0
    assert not runs.exists() or list(runs.iterdir()) == []


@pytest.mark.parametrize("options, message", [
    (["--count", "5"], "set at least two of --count, --duration, --frequency"),
    (["--count", "20", "--duration", "1", "--frequency", "100"], "--count=20 contradicts"),
    (["--ammeter", "fluke"], "unknown ammeter"),
])
def test_usage_errors_exit_with_2(config, capsys, options, message):
    """Invalid options are usage errors (exit code 2) that name the option the user typed."""
    path, _ = config
    with pytest.raises(SystemExit) as exit_info:
        main(["--config", str(path), *options])
    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err


def test_config_error_exits_with_1(tmp_path, monkeypatch, capsys):
    """An invalid config file is reported and the run exits with code 1 before anything is measured."""
    monkeypatch.setattr(logger_module, "PROJECT_ROOT", tmp_path)
    path = tmp_path / "config.yaml"
    path.write_text("ammeters: {}\n")
    assert main(["--config", str(path)]) == 1
    assert "Configuration error" in capsys.readouterr().err


def test_emulator_that_cannot_start_exits_with_1_but_others_are_tested(config, capsys):
    """A busy emulator port is an error of the run (exit 1); the other ammeters are still tested."""
    path, _ = config
    data = yaml.safe_load(path.read_text())
    # The blocker accepts connections but never answers; a short timeout keeps the test fast
    data["ammeters"]["greenlee"]["timeout"] = 0.2
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    with socket.socket() as blocker:
        blocker.bind(("localhost", data["ammeters"]["greenlee"]["port"]))
        blocker.listen()
        assert main(["--config", str(path), "--ammeter", "greenlee", "--ammeter", "entes", "--no-save"]) == 1
    captured = capsys.readouterr()
    assert "'greenlee' on port" in captured.err
    assert "=== entes: 3 measurements, 3 ok" in captured.out
