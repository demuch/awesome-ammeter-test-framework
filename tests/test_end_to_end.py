"""End-to-end tests: the whole path from config.yaml to the archive, as python -m src.run runs it."""
import subprocess
import sys

import pytest
import yaml

from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import PROJECT_ROOT
from src.utils.emulators import start_emulators
from tests.conftest import EMULATORS, free_port

pytestmark = pytest.mark.integration


@pytest.fixture
def framework(tmp_path):
    """
    Framework with all three emulators on free ports, short sampling and an archive in a temporary folder.

    :returns: The framework; its emulators are already running.
    """
    config = {
        "testing": {"sampling": {"measurements_count": 5, "sampling_frequency_hz": 20}},
        "ammeters": {name: {"port": free_port(), "command": command.decode(), "emulator": class_path}
                     for name, (class_path, command) in EMULATORS.items()},
        "result_management": {"results_dir": str(tmp_path / "runs")},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))  # Keep the ammeter order, safe_dump sorts by default
    framework = AmmeterTestFramework(path)
    start_emulators(framework.ammeters)
    return framework


def test_every_ammeter_measured_saved_and_reloaded(framework):
    """Each ammeter is measured without failures, archived, and the archived run equals the result."""
    for name in framework.ammeters:
        result = framework.run_test(name)
        assert len(result.series.samples) == 5
        assert result.success_rate == 1.0, result.series.failed
        record = framework.save(result)
        assert framework.archive.load(record.run_id) == record
        assert f"=== {name}: 5 measurements, 5 ok" in framework.report(result)


def test_unknown_ammeter_is_rejected(framework):
    """run_test() names the configured ammeters when asked for an unknown one."""
    with pytest.raises(ValueError, match="configured: \\['greenlee', 'entes', 'circutor'\\]"):
        framework.run_test("fluke")


def test_sample_results_in_repository_are_readable():
    """The committed sample_results/ can be read by the current code (they must be regenerated if the format changes)."""
    completed = subprocess.run([sys.executable, "-m", "src.results", "--dir", "sample_results", "list"],
                               cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == "", completed.stderr  # No skipped (unreadable) files
    assert len(completed.stdout.splitlines()) == 1 + 10  # Header and ten runs
