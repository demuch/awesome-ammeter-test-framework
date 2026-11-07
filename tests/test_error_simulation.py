"""Tests of error simulation in the emulators, its configuration and how it is archived."""
import collections
from dataclasses import replace

import pytest

from Ammeters.error_simulation import FAULTS, ErrorSimulation
from src.results import main as results_main
from src.testing.ammeter import Ammeter, load_ammeters
from src.testing.archive import ResultArchive
from src.utils.config import ConfigError
from src.utils.emulators import start_emulators
from tests.conftest import EMULATORS, free_port
from tests.test_archive import make_record

GREENLEE, GREENLEE_COMMAND = EMULATORS["greenlee"]


def emulated(errors: ErrorSimulation, timeout: float = 5.0) -> Ammeter:
    """
    Starts a Greenlee emulator with error simulation on a free port.

    :param errors: The error simulation.
    :param timeout: Timeout of the returned ammeter in seconds.
    :returns: The ammeter; its emulator already accepts connections.
    """
    ammeter = Ammeter("greenlee", free_port(), GREENLEE_COMMAND, timeout=timeout, emulator=GREENLEE,
                      simulate_errors=errors)
    start_emulators({"greenlee": ammeter})
    return ammeter


# --- picking faults ---

@pytest.mark.parametrize("fault", FAULTS)
def test_probability_one_always_picks_that_fault(fault):
    """A probability of 1 means every request gets this fault."""
    errors = ErrorSimulation(**{fault: 1.0})
    generator = errors.new_generator()
    assert {errors.pick(generator) for _ in range(100)} == {fault}


def test_no_probabilities_never_pick_a_fault():
    """Without probabilities every request gets a normal reply."""
    errors = ErrorSimulation()
    generator = errors.new_generator()
    assert {errors.pick(generator) for _ in range(100)} == {None}


def test_faults_follow_their_probabilities():
    """Over many requests each fault appears with its probability, and the rest are normal."""
    errors = ErrorSimulation(error_reply=0.1, garbage=0.2, no_reply=0.05, slow_reply=0.15, seed=1)
    generator = errors.new_generator()
    counts = collections.Counter(errors.pick(generator) for _ in range(100_000))
    expected = {"error_reply": 0.1, "garbage": 0.2, "no_reply": 0.05, "slow_reply": 0.15, None: 0.5}
    for fault, share in expected.items():
        assert counts[fault] / 100_000 == pytest.approx(share, abs=0.01), fault


def test_same_seed_gives_same_faults():
    """With a seed the same requests fail on every run; that is what makes tests with faults repeatable."""
    errors = ErrorSimulation(error_reply=0.3, garbage=0.3, seed=42)
    first, second = errors.new_generator(), errors.new_generator()
    assert [errors.pick(first) for _ in range(50)] == [errors.pick(second) for _ in range(50)]


# --- emulator replies ---

@pytest.mark.integration
@pytest.mark.parametrize("fault, message", [
    ("error_reply", "ERROR: simulated failure"),
    ("garbage", "not a number"),
    ("no_reply", "empty reply"),
])
def test_each_fault_becomes_a_failed_measurement(fault, message):
    """Each simulated fault reaches the framework as a failed measurement with the matching reason."""
    m = emulated(ErrorSimulation(**{fault: 1.0})).measure()
    assert not m.ok and message in m.error


@pytest.mark.integration
def test_slow_reply_is_correct_but_late():
    """A slow reply is still a valid measurement, only delayed."""
    m = emulated(ErrorSimulation(slow_reply=1.0, slow_reply_s=0.2)).measure()
    assert m.ok and m.duration_s >= 0.2


@pytest.mark.integration
def test_slow_reply_longer_than_timeout_is_a_timeout():
    """A reply slower than the client's timeout ends as a timeout."""
    m = emulated(ErrorSimulation(slow_reply=1.0, slow_reply_s=0.5), timeout=0.1).measure()
    assert not m.ok and "timed out" in m.error


@pytest.mark.integration
def test_emulators_with_same_seed_fail_on_same_requests():
    """Two emulators with the same seed fail on the same request numbers."""
    errors = ErrorSimulation(error_reply=0.3, seed=7)
    first, second = emulated(errors), emulated(errors)
    first_results = [first.measure().ok for _ in range(30)]
    second_results = [second.measure().ok for _ in range(30)]
    assert first_results == second_results
    assert 0 < first_results.count(False) < 30  # Some requests failed, but not all


@pytest.mark.integration
def test_without_simulation_every_reply_is_valid(emulator):
    """An emulator without simulate_errors behaves exactly as before."""
    ammeter = emulator("greenlee")
    assert all(ammeter.measure().ok for _ in range(50))


# --- configuration ---

def settings(simulate_errors, **extra):
    """
    :param simulate_errors: Value of the simulate_errors key.
    :param extra: Other settings of the ammeter, e.g. ``emulator=None``.
    :returns: A config with one ammeter ``g``.
    """
    ammeter = {"port": 5000, "command": "X", "emulator": GREENLEE, "simulate_errors": simulate_errors}
    ammeter.update(extra)
    return {"ammeters": {"g": {k: v for k, v in ammeter.items() if v is not None}}}


def test_valid_simulation_settings():
    """Missing probabilities are 0 and slow_reply_s has a default."""
    errors = load_ammeters(settings({"garbage": 0.2, "seed": 3}))["g"].simulate_errors
    assert errors == ErrorSimulation(garbage=0.2, seed=3)


@pytest.mark.parametrize("simulate_errors, extra, message", [
    ({"garbge": 0.1}, {}, "unknown key"),
    ({"garbage": 1.5}, {}, "probability from 0 to 1"),
    ({"garbage": -0.1}, {}, "probability from 0 to 1"),
    ({"garbage": True}, {}, "probability from 0 to 1"),
    ({"garbage": "10%"}, {}, "probability from 0 to 1"),
    ({"garbage": 0.6, "no_reply": 0.6}, {}, "add up to 1.2"),
    ({"slow_reply": 0.1, "slow_reply_s": 0}, {}, "slow_reply_s must be a positive"),
    ({"seed": "abc"}, {}, "seed must be a whole number"),
    ({"seed": 1.5}, {}, "seed must be a whole number"),
    ("often", {}, "must be a mapping"),
    ({"garbage": 0.1}, {"emulator": None}, "needs an 'emulator'"),
])
def test_invalid_simulation_settings(simulate_errors, extra, message):
    """Every invalid setting is a ConfigError; a typo in a fault name is not silently ignored."""
    with pytest.raises(ConfigError, match=message):
        load_ammeters(settings(simulate_errors, **extra))


# --- archive ---

def test_simulation_settings_survive_the_archive(tmp_path, clock, capsys):
    """A run with simulated faults keeps its settings in the archive, and show names them."""
    errors = ErrorSimulation(error_reply=0.1, slow_reply=0.2, slow_reply_s=0.3, seed=42)
    record = make_record(clock)
    record = replace(record, ammeter=replace(record.ammeter, simulate_errors=errors))
    archive = ResultArchive(tmp_path)
    archive.save(record)
    assert archive.load(record.run_id) == record
    results_main(["--dir", str(tmp_path), "show", record.run_id])
    assert "Simulated  error_reply 10%, slow_reply 20% (slow replies 0.3 s, seed 42)" in capsys.readouterr().out
