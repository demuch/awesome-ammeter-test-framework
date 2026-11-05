"""Tests of the unified API Ammeter.measure() and of TestLogger."""
import logging

import pytest

from src.testing.ammeter import Ammeter
from src.utils import logger as logger_module
from src.utils.logger import TestLogger
from tests.conftest import free_port


@pytest.mark.integration
def test_measure_returns_successful_measurement(fake_server):
    """A valid reply becomes a Measurement with the value, the ammeter name and the request duration."""
    server = fake_server(chunks=[b"0.42"])
    m = Ammeter("greenlee", server.port, b"CMD").measure()
    assert (m.ammeter, m.value, m.error, m.ok) == ("greenlee", 0.42, None, True)
    assert m.duration_s > 0


@pytest.mark.integration
@pytest.mark.parametrize("port_kind, message", [
    ("closed", "ConnectionRefusedError"),
    ("error-reply", "unknown command"),
])
def test_measure_returns_failed_measurement_instead_of_raising(fake_server, port_kind, message):
    """An unreachable ammeter or a bad reply does not raise: it is a failed Measurement with the reason."""
    port = free_port() if port_kind == "closed" else fake_server(chunks=[b"ERROR: unknown command"]).port
    m = Ammeter("greenlee", port, b"CMD").measure()
    assert (m.value, m.ok) == (None, False)
    assert message in m.error


@pytest.mark.integration
def test_measure_does_not_hide_framework_errors(fake_server):
    """Only ammeter errors become failed measurements; a bug in the framework still raises."""
    # A listening server is needed: otherwise the connection is refused (an ammeter error) before the bug is reached
    server = fake_server(chunks=[b"1.0"])
    broken = Ammeter("greenlee", server.port, "CMD")  # str instead of bytes: a programming error, not an ammeter failure
    with pytest.raises(TypeError):
        broken.measure()


# --- TestLogger (FIXES.md, Fix 8) ---

@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    """
    Makes TestLogger write into a temporary folder instead of the project's results/logs.

    :returns: The folder the log files are written to.
    """
    monkeypatch.setattr(logger_module, "PROJECT_ROOT", tmp_path)
    return tmp_path / "results" / "logs"


def test_logger_writes_all_levels_to_file(log_dir):
    """The log file gets every level including DEBUG, with time and level."""
    log = TestLogger("unit")
    log.debug("d"), log.info("i"), log.warning("w"), log.error("e")
    lines = next(log_dir.glob("*_unit.log")).read_text().splitlines()
    assert [line.split(" ", 2)[2] for line in lines] == [
        "[DEBUG] test_unit: d", "[INFO] test_unit: i", "[WARNING] test_unit: w", "[ERROR] test_unit: e"]


def test_logger_console_shows_info_and_above(log_dir, capsys):
    """The console gets INFO and above, so DEBUG details do not clutter it."""
    log = TestLogger("console")
    log.debug("hidden")
    log.info("shown")
    err = capsys.readouterr().err
    assert "shown" in err and "hidden" not in err


def test_second_logger_with_same_name_does_not_duplicate_lines(log_dir, capsys):
    """getLogger() returns the same object for a name; old handlers are removed, so each line appears once."""
    TestLogger("twice")
    TestLogger("twice").info("once")
    assert capsys.readouterr().err.count("once") == 1
    assert len(logging.getLogger("test_twice").handlers) == 2  # One file handler and one console handler
