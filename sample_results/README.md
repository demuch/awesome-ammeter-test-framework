# Sample Test Results

Archived runs produced by this version of the framework, one JSON file per run.

- Six runs from two executions of `python -m src.run`: two runs for each emulated ammeter
  (Greenlee, ENTES, CIRCUTOR), 20 measurements over 2 s each.
- One run of `lab_device` (`python -m src.run --config` with a config that has only this device): a device
  without an emulator, so nothing answers on its port.
  It shows how failed measurements are archived and reported (0% success, the error and its count).
- `run_output.txt`: console output of the second execution.

View them without changing the configuration:

```sh
python -m src.results --dir sample_results list
python -m src.results --dir sample_results show 20261107-081400
python -m src.results --dir sample_results compare 20261107-081348 20261107-081354
```

Run IDs can be shortened to any unique beginning.
