"""
Plots of archived runs. Needs matplotlib (``pip install -r requirements-plot.txt``); the rest of the framework does not.
matplotlib is imported only inside the plotting functions, so importing this module never fails.
"""
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from src.testing.archive import RunRecord
from src.utils.config import ConfigError

# Panels of a single-run figure, in figure order; also the allowed values of analysis.visualization.plot_types
PLOT_TYPES = ("values", "histogram", "response_time", "timing")

INSTALL_HINT = "plots need matplotlib: pip install -r requirements-plot.txt"


class PlotError(Exception):
    """A plot cannot be drawn or written: matplotlib is missing, the runs have nothing to plot, or the file fails."""


class MatplotlibMissingError(PlotError):
    """matplotlib is not installed; an expected situation, since plots are optional."""


@dataclass(frozen=True)
class Theme:
    """
    Colors of one theme. Light and dark are separately chosen steps, not an inversion of each other.

    :ivar surface: Background of the figure.
    :ivar text: Titles and values.
    :ivar text_secondary: Axis labels.
    :ivar muted: Tick labels.
    :ivar grid: Gridlines (hairline, solid).
    :ivar axis: Axis lines.
    :ivar series: The one data series of every panel.
    :ivar failed: Status color for failed measurements; always shown with a legend label.
    :ivar late: Status color for late measurements; always shown with a legend label.
    """
    surface: str
    text: str
    text_secondary: str
    muted: str
    grid: str
    axis: str
    series: str
    failed: str
    late: str


THEMES: Dict[str, Theme] = {
    "light": Theme("#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#2a78d6", "#d03b3b", "#ec835a"),
    "dark": Theme("#1a1a19", "#ffffff", "#c3c2b7", "#898781", "#2c2c2a", "#383835", "#3987e5", "#d03b3b", "#ec835a"),
}


def plot_types_from_config(config: Dict) -> Tuple[bool, Tuple[str, ...]]:
    """
    Reads ``analysis.visualization``.

    :param config: Configuration as returned by :func:`src.utils.config.load_config`.
    :returns: Whether ``python -m src.run`` saves a plot of every archived run (``enabled``, default ``True``), and the
        panels of a single-run figure (``plot_types``; all of :data:`PLOT_TYPES` if missing or empty).
    :raises ConfigError: ``enabled`` is not true/false, ``plot_types`` is not a list, or it names an unknown panel.
    """
    section = (config.get("analysis") or {}).get("visualization") or {}
    if not isinstance(section, dict):
        raise ConfigError("analysis.visualization must be a mapping")
    enabled = section.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigError(f"analysis.visualization.enabled must be true or false, got {enabled!r}")
    selected = section.get("plot_types")
    if not selected:
        return enabled, PLOT_TYPES
    if not isinstance(selected, list):
        raise ConfigError(f"analysis.visualization.plot_types must be a list, got {selected!r}")
    unknown = [name for name in selected if name not in PLOT_TYPES]
    if unknown:
        raise ConfigError(f"analysis.visualization.plot_types: unknown plot(s) {unknown}; known: {list(PLOT_TYPES)}")
    return enabled, tuple(name for name in PLOT_TYPES if name in selected)


def plot_run(record: RunRecord, path: Path, plot_types: Sequence[str] = PLOT_TYPES, theme: str = "light") -> Path:
    """
    Draws one run: each selected panel is its own chart with its own axis.

    :param record: The run.
    :param path: PNG file to write; its folder is created if needed.
    :param plot_types: Panels to draw, see :data:`PLOT_TYPES`.
    :param theme: ``"light"`` or ``"dark"``.
    :returns: ``path``.
    :raises PlotError: matplotlib is not installed.
    """
    plt = _pyplot()
    colors = THEMES[theme]
    series = record.result.series
    rows, cols = (1, len(plot_types)) if len(plot_types) <= 2 else (2, 2)
    fig, axes = plt.subplots(rows, cols, figsize=(6 * cols, 3.6 * rows), squeeze=False)
    fig.patch.set_facecolor(colors.surface)
    config = series.config
    fig.suptitle(f"{record.result.ammeter}: {len(series.samples)} measurements at {config.frequency_hz:g} Hz, "
                 f"{record.result.success_rate:.0%} ok\nrun {record.run_id}",
                 color=colors.text, fontsize=12, x=0.01, ha="left")

    ok = [s for s in series.samples if s.measurement.ok]
    failed = [s for s in series.samples if not s.measurement.ok]
    flat = [ax for row in axes for ax in row]
    for ax, name in zip(flat, plot_types):
        _style(ax, colors)
        if name == "values":
            ax.set_title("Values over time", **_title(colors))
            ax.plot([s.started_s for s in ok], [s.measurement.value for s in ok], color=colors.series,
                    linewidth=1.5, marker="o", markersize=5, label="measured")
            if failed:
                # A failed measurement has no value: mark it on the bottom edge, apart from the data
                # (x in data coordinates, y in axes coordinates)
                ax.plot([s.started_s for s in failed], [0.03] * len(failed), linestyle="none", marker="x",
                        markersize=7, markeredgewidth=2, color=colors.failed, label=f"failed ({len(failed)})",
                        transform=ax.get_xaxis_transform(), clip_on=False)
                _legend(ax, colors)
            ax.set_xlabel("time since start (s)", color=colors.text_secondary)
            ax.set_ylabel("current (A)", color=colors.text_secondary)
        elif name == "histogram":
            ax.set_title("Distribution of values", **_title(colors))
            values = [s.measurement.value for s in ok]
            if values:
                bins = max(5, min(20, round(math.sqrt(len(values)))))
                # A 2 px gap in the surface color separates the bars
                ax.hist(values, bins=bins, color=colors.series, edgecolor=colors.surface, linewidth=2)
            ax.set_xlabel("current (A)", color=colors.text_secondary)
            ax.set_ylabel("measurements", color=colors.text_secondary)
        elif name == "response_time":
            ax.set_title("Response time", **_title(colors))
            ax.plot([s.started_s for s in series.samples], [s.measurement.duration_s * 1000 for s in series.samples],
                    color=colors.series, linewidth=1.5, marker="o", markersize=5)
            ax.set_xlabel("time since start (s)", color=colors.text_secondary)
            ax.set_ylabel("response time (ms)", color=colors.text_secondary)
        elif name == "timing":
            ax.set_title("Start delay against the schedule", **_title(colors))
            ax.axhline(0, color=colors.axis, linewidth=1)
            ax.plot([s.started_s for s in series.samples], [s.lag_s * 1000 for s in series.samples],
                    color=colors.series, linewidth=1.5, marker="o", markersize=5, label="on schedule")
            late = [s for s in series.samples if s.late]
            if late:
                ax.plot([s.started_s for s in late], [s.lag_s * 1000 for s in late], linestyle="none", marker="o",
                        markersize=8, color=colors.late, markeredgecolor=colors.surface, markeredgewidth=2,
                        label=f"late ({len(late)})")
                _legend(ax, colors)
            ax.set_xlabel("time since start (s)", color=colors.text_secondary)
            ax.set_ylabel("delay (ms)", color=colors.text_secondary)
    for ax in flat[len(plot_types):]:
        ax.set_visible(False)
    return _save(fig, path)


def plot_comparison(records: Sequence[RunRecord], path: Path, theme: str = "light") -> Path:
    """
    Compares runs side by side: values relative to each run's own mean (ammeters have very different scales), and
    response times. Runs are named on the axis, so all boxes share one color.

    :param records: Two or more runs.
    :param path: PNG file to write; its folder is created if needed.
    :param theme: ``"light"`` or ``"dark"``.
    :returns: ``path``.
    :raises PlotError: matplotlib is not installed, or no run has successful values.
    """
    plt = _pyplot()
    colors = THEMES[theme]
    labels: List[str] = []
    relative: List[List[float]] = []
    response: List[List[float]] = []
    for record in records:
        values = record.result.series.values
        mean = record.result.values.mean
        if not values or not mean:
            continue  # No values, or a mean of 0: values cannot be made relative
        labels.append(f"{record.result.ammeter}\n{record.started_at:%m-%d %H:%M:%S}")
        relative.append([v / mean for v in values])
        response.append([s.measurement.duration_s * 1000 for s in record.result.series.samples])
    if not labels:
        raise PlotError("none of the runs has successful measurements to compare")

    # One panel above the other, each as wide as the runs need
    fig, (left, right) = plt.subplots(2, 1, figsize=(max(8, 1.4 * len(labels) + 2), 7.5))
    fig.patch.set_facecolor(colors.surface)
    fig.suptitle(f"Comparison of {len(labels)} runs", color=colors.text, fontsize=12, x=0.01, ha="left")
    for ax, data, title, ylabel in ((left, relative, "Values relative to the run's own mean", "value / mean"),
                                    (right, response, "Response time", "response time (ms)")):
        _style(ax, colors)
        ax.set_title(title, **_title(colors))
        boxes = ax.boxplot(data, patch_artist=True, widths=0.5,
                           medianprops={"color": colors.text, "linewidth": 1.5},
                           whiskerprops={"color": colors.series, "linewidth": 1.5},
                           capprops={"color": colors.series, "linewidth": 1.5},
                           flierprops={"marker": "o", "markersize": 5, "markerfacecolor": colors.series,
                                       "markeredgecolor": colors.surface})
        for box in boxes["boxes"]:
            box.set(facecolor=colors.series, alpha=0.35, edgecolor=colors.series, linewidth=1.5)
        ax.set_xticks(range(1, len(labels) + 1))
        ax.set_xticklabels(labels, color=colors.muted)
        ax.set_ylabel(ylabel, color=colors.text_secondary)
    left.axhline(1, color=colors.axis, linewidth=1)  # 1 = the run's own mean
    return _save(fig, path)


def _pyplot():
    """
    :returns: ``matplotlib.pyplot`` with the non-interactive Agg backend (writes files, needs no display).
    :raises MatplotlibMissingError: matplotlib is not installed.
    """
    try:
        import matplotlib
    except ImportError as e:
        raise MatplotlibMissingError(INSTALL_HINT) from e
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _style(ax, colors: Theme) -> None:
    """
    Recessive chrome: solid hairline grid on the value axis only, no top or right frame.

    :param ax: Axes to style.
    :param colors: Theme colors.
    """
    ax.set_facecolor(colors.surface)
    ax.grid(axis="y", color=colors.grid, linewidth=0.8, linestyle="-")
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(colors.axis)
    ax.tick_params(colors=colors.muted, labelsize=9)


def _title(colors: Theme) -> Dict:
    """
    :param colors: Theme colors.
    :returns: Keyword arguments for a panel title.
    """
    return {"color": colors.text, "fontsize": 11, "loc": "left"}


def _legend(ax, colors: Theme) -> None:
    """
    Adds a legend in the theme's colors; used only where a panel has two kinds of marks.

    :param ax: Axes with labelled marks.
    :param colors: Theme colors.
    """
    # Above the plot area, right of the title, so it never covers data
    legend = ax.legend(frameon=False, fontsize=9, loc="lower right", bbox_to_anchor=(1, 1), ncol=2,
                       borderaxespad=0.2)
    for text in legend.get_texts():
        text.set_color(colors.text_secondary)


def _save(fig, path: Path) -> Path:
    """
    :param fig: Figure to write; it is closed in any case, so failed plots do not pile up in memory.
    :param path: PNG file; its folder is created if needed.
    :returns: ``path``.
    :raises PlotError: The folder cannot be created or the file cannot be written.
    """
    import matplotlib.pyplot as plt
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.tight_layout()
        fig.savefig(path, dpi=130, facecolor=fig.get_facecolor())
    except OSError as e:
        raise PlotError(f"cannot write plot {path}: {e}") from e
    finally:
        plt.close(fig)
    return path
