# Sample Test Results

Archived runs produced by this version of the framework, one JSON file per run.

- Six runs from two executions of `python examples/run_tests.py`: two runs for each emulated ammeter
  (Greenlee, ENTES, CIRCUTOR), 20 measurements over 2 s each.
- One run of `lab_device`: a device without an emulator, so nothing answers on its port.
  It shows how failed measurements are archived and reported (0% success, the error and its count).
- `run_tests_output.txt`: console output of the second execution.

View them without changing the configuration:

```sh
python -m src.results --dir sample_results list
python -m src.results --dir sample_results show 20261105-185442
python -m src.results --dir sample_results compare 20261105-185430 20261105-185436
```

Run IDs can be shortened to any unique beginning.
