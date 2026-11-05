"""Tests of loading config.yaml, creating ammeters from it and starting emulators."""
import socket

import pytest

from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from src.testing.ammeter import Ammeter, load_ammeters
from src.utils.config import DEFAULT_CONFIG_PATH, ConfigError, load_config
from src.utils.emulators import EmulatorStartError, load_emulator_class, start_emulators
from tests.conftest import EMULATORS, free_port

GREENLEE = "Ammeters.Greenlee_Ammeter.GreenleeAmmeter"


# --- load_config ---

def test_project_config_matches_readme():
    """config.yaml uses the ports and commands from README.md."""
    ammeters = load_ammeters(load_config(DEFAULT_CONFIG_PATH))
    assert {name: (a.port, a.command) for name, a in ammeters.items()} == {
        "greenlee": (5000, b"MEASURE_GREENLEE -get_measurement"),
        "entes": (5001, b"MEASURE_ENTES -get_data"),
        "circutor": (5002, b"MEASURE_CIRCUTOR -get_measurement"),
    }


def test_missing_config_file(tmp_path):
    """A missing file is a ConfigError, not a raw FileNotFoundError."""
    with pytest.raises(ConfigError, match="Cannot read config file"):
        load_config(tmp_path / "missing.yaml")


@pytest.mark.parametrize("text, message", [
    ("ammeters: [unclosed\n", "Invalid YAML"),
    ("- just\n- a list\n", "must be a mapping"),
    ("", "must be a mapping"),
])
def test_invalid_config_file(tmp_path, text, message):
    """Broken YAML or a file that is not a mapping of sections is a ConfigError."""
    path = tmp_path / "config.yaml"
    path.write_text(text)
    with pytest.raises(ConfigError, match=message):
        load_config(path)


# --- load_ammeters ---

def test_ammeter_defaults():
    """host, timeout and emulator are optional."""
    ammeters = load_ammeters({"ammeters": {"g": {"port": 5000, "command": "CMD"}}})
    assert ammeters["g"] == Ammeter("g", 5000, b"CMD", "localhost", 5.0, None)


@pytest.mark.parametrize("section, message", [
    (None, "missing or empty"),
    ({}, "missing or empty"),
    ({"e": "not a mapping"}, "must be a mapping"),
    ({"e": {"command": "X"}}, "missing 'port'"),
    ({"e": {"port": 5001}}, "missing 'command'"),
    ({"e": {"port": "5001", "command": "X"}}, "'port' must be an integer"),
    ({"e": {"port": True, "command": "X"}}, "'port' must be an integer"),
    ({"e": {"port": 0, "command": "X"}}, "'port' must be an integer"),
    ({"e": {"port": 70000, "command": "X"}}, "'port' must be an integer"),
    ({"e": {"port": 5001, "command": ""}}, "'command' must be a non-empty string"),
    ({"e": {"port": 5001, "command": 42}}, "'command' must be a non-empty string"),
    ({"e": {"port": 5001, "command": "X", "host": ""}}, "'host' must be a non-empty string"),
    ({"e": {"port": 5001, "command": "X", "timeout": 0}}, "'timeout' must be a positive number"),
    ({"e": {"port": 5001, "command": "X", "timeout": True}}, "'timeout' must be a positive number"),
    ({"e": {"port": 5001, "command": "X", "emulator": "NoDot"}}, "'emulator' must be an import path"),
    ({"e": {"port": 5001, "command": "X", "emulator": 42}}, "'emulator' must be an import path"),
    ({"e": {"port": 5001, "command": "X", "host": "192.168.1.50", "emulator": GREENLEE}}, "runs on this machine"),
    ({"a": {"port": 5001, "command": "X"}, "b": {"port": 5001, "command": "Y"}}, "both use localhost:5001"),
])
def test_invalid_ammeter_settings(section, message):
    """Every invalid ammeter setting gives a ConfigError that names the problem."""
    with pytest.raises(ConfigError, match=message):
        load_ammeters({"ammeters": section})


# --- emulator classes ---

def test_load_emulator_class():
    """A valid import path gives the emulator class."""
    assert load_emulator_class(GREENLEE) is GreenleeAmmeter


@pytest.mark.parametrize("path, message", [
    ("Ammeters.Greenlee_Amemter.GreenleeAmmeter", "No module named"),
    ("Ammeters.Greenlee_Ammeter.Nope", "has no 'Nope'"),
    ("Ammeters.client.AmmeterError", "not a subclass of AmmeterEmulatorBase"),
    ("Ammeters.base_ammeter.AmmeterEmulatorBase", "is abstract"),
])
def test_invalid_emulator_class(path, message):
    """A wrong import path or a class that is not a concrete emulator is a ConfigError."""
    with pytest.raises(ConfigError, match=message):
        load_emulator_class(path)


@pytest.mark.integration
def test_nothing_starts_if_one_emulator_class_is_wrong():
    """All classes are checked before any emulator starts, so a typo leaves no half-started setup."""
    good_port = free_port()
    ammeters = {
        "good": Ammeter("good", good_port, b"X", emulator=GREENLEE),
        "bad": Ammeter("bad", free_port(), b"X", emulator="Ammeters.Nope.X"),
    }
    with pytest.raises(ConfigError):
        start_emulators(ammeters)
    with socket.socket() as s:
        assert s.connect_ex(("localhost", good_port)) != 0, "the valid emulator was started anyway"


@pytest.mark.integration
def test_busy_port_is_reported_and_other_emulators_start():
    """A port taken by another process gives EmulatorStartError naming it; the other emulators still start."""
    with socket.socket() as blocker:
        blocker.bind(("localhost", 0))
        blocker.listen()
        busy = blocker.getsockname()[1]
        free = free_port()
        ammeters = {
            "blocked": Ammeter("blocked", busy, b"X", emulator=GREENLEE),
            "ok": Ammeter("ok", free, EMULATORS["greenlee"][1], emulator=GREENLEE),
        }
        with pytest.raises(EmulatorStartError, match=f"'blocked' on port {busy}"):
            start_emulators(ammeters)
        assert ammeters["ok"].measure().ok


@pytest.mark.integration
def test_real_device_without_emulator_is_skipped():
    """An ammeter without 'emulator' is a real device: nothing is started for it."""
    port = free_port()
    start_emulators({"real": Ammeter("real", port, b"X")})
    with socket.socket() as s:
        assert s.connect_ex(("localhost", port)) != 0
