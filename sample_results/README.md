# Sample Test Results

Archived runs produced by this version of the framework, one JSON file per run.

- Six runs from two executions of `python -m src.run`: two runs for each emulated ammeter
  (Greenlee, ENTES, CIRCUTOR), 20 measurements over 2 s each.
- One run of `lab_device` (`python -m src.run --config` with a config that has only this device): a device
  without an emulator, so nothing answers on its port.
  It shows how failed measurements are archived and reported (0% success, the error and its count).
- `run_output.txt`: console output of the second execution.
- Three runs of `python -m src.run --config config/error_simulation.yaml` (saving turned on): Greenlee with
  simulated `ERROR` replies, ENTES with missing replies, CIRCUTOR with slow replies and late measurements;
  `error_simulation_output.txt` is their console output.
- `plots/`: the plots shown in the main README, each in a light and a dark version.

View them without changing the configuration:

```sh
python -m src.results --dir sample_results list
python -m src.results --dir sample_results show 20261107-081400
python -m src.results --dir sample_results compare 20261107-081348 20261107-081354
python -m src.results --dir sample_results show 20261107-101735      # shows the simulated faults
python -m src.results --dir sample_results plot 20261107-101731      # needs requirements-plot.txt
```

Run IDs can be shortened to any unique beginning.
