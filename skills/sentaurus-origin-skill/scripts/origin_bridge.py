#!/usr/bin/env python3
"""Safe Sentaurus DF-ISE/table to Origin automation bridge."""

from __future__ import annotations

import argparse
import csv
import difflib
import gc
import importlib.metadata
import importlib.util
import json
import math
import os
import platform
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


VERSION = "1.3.0"
DEFAULT_ORIGIN_OUTPUT_ROOT = Path(r"E:\Pictures\OriginPlot")
DEFAULT_TEMP_PROJECT_FOLDER = "Origin-Temp"
SKILL_ROOT = Path(__file__).resolve().parent.parent
FIGURE_TEMPLATES = {
    "single-y": SKILL_ROOT / "assets" / "origin-single-y-arial30.otpu",
    "double-y": SKILL_ROOT / "assets" / "origin-double-y-arial30.otpu",
}
DEFAULT_FIGURE_STYLE = {
    "font": "Arial",
    "font_size": 30,
    "bold": True,
    "axis_thickness": 4,
    "data_line_width": 4,
    "legend_border": False,
    "major_ticks": 7,
    "scientific_format": "power",
    "page_width": 6432,
    "page_height": 4923,
    "page_dpi": 600,
    "page_orientation": 2,
    "page_update_to_printer": 1,
}
FIGURE_GEOMETRY = {
    "single-y": {"left": 18, "top": 12, "width": 68, "height": 72},
    "double-y": {"left": 17, "top": 12, "width": 64, "height": 72},
}
COLORBLIND_SAFE = [
    "#0072B2",
    "#D55E00",
    "#009E73",
    "#CC79A7",
    "#E69F00",
    "#56B4E9",
    "#000000",
]
FLOAT_RE = re.compile(
    r"(?<![A-Za-z_])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?|[-+]?(?:nan|inf)",
    re.IGNORECASE,
)


@dataclass
class Table:
    path: Path
    format: str
    columns: list[str]
    rows: list[list[Any]]

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def values(self, name: str) -> list[float]:
        resolved = resolve_column(self.columns, name)
        index = self.columns.index(resolved)
        values: list[float] = []
        for row_number, row in enumerate(self.rows, start=2):
            value = row[index]
            if value is None or (isinstance(value, str) and not value.strip()):
                values.append(float("nan"))
                continue
            try:
                values.append(float(value))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{self.path}:{row_number} column {resolved!r} contains non-numeric value {value!r}"
                ) from exc
        return values


PRESETS: dict[str, dict[str, Any]] = {
    "idvg": {
        "x": ["gate OuterVoltage", "gate InnerVoltage", "Vg", "V_G"],
        "y": ["drain TotalCurrent", "Id", "I_D"],
        "x_title": r"V\-(G) (V)",
        "y_title": r"|I\-(D)| (A)",
        "x_scale": "linear",
        "y_scale": "log10",
        "abs_y": True,
    },
    "idvd": {
        "x": ["drain OuterVoltage", "drain InnerVoltage", "Vd", "V_D"],
        "y": ["drain TotalCurrent", "Id", "I_D"],
        "x_title": r"V\-(D) (V)",
        "y_title": r"I\-(D) (A)",
        "x_scale": "linear",
        "y_scale": "linear",
        "abs_y": False,
    },
    "bv": {
        "x": ["drain InnerVoltage", "drain OuterVoltage", "Vd", "V_D"],
        "y": ["drain TotalCurrent", "Id", "I_D"],
        "x_title": r"V\-(D) (V)",
        "y_title": r"|I\-(D)| (A)",
        "x_scale": "linear",
        "y_scale": "log10",
        "abs_y": True,
    },
    "transient": {
        "x": ["time", "Time", "t"],
        "y": ["drain TotalCurrent", "Id", "I_D"],
        "x_title": "Time (s)",
        "y_title": r"I\-(D) (A)",
        "x_scale": "linear",
        "y_scale": "linear",
        "abs_y": False,
    },
    "frequency": {
        "x": ["Frequency_GHz", "Frequency", "frequency", "freq"],
        "y": [],
        "x_title": "Frequency (GHz)",
        "y_title": "",
        "x_scale": "log10",
        "y_scale": "linear",
        "abs_y": False,
    },
}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"{path} is not UTF-8 DF-ISE text. Export binary/proprietary data through "
            "Sentaurus Visual or Inspect before using this bridge."
        ) from exc


def parse_dfise(path: Path) -> Table:
    text = read_text(path)
    if not text.lstrip().startswith("DF-ISE text"):
        raise ValueError(
            f"{path} is not a supported DF-ISE text file. Do not guess a binary .plt layout."
        )
    info_match = re.search(r"\bInfo\s*\{(.*?)\}\s*Data\s*\{", text, re.DOTALL)
    data_match = re.search(r"\bData\s*\{(.*?)\}\s*$", text, re.DOTALL)
    if not info_match or not data_match:
        raise ValueError(f"{path} does not contain complete Info and Data blocks")
    datasets_match = re.search(r"\bdatasets\s*=\s*\[(.*?)\]", info_match.group(1), re.DOTALL)
    if not datasets_match:
        raise ValueError(f"{path} has no datasets list")
    columns = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', datasets_match.group(1))
    columns = [bytes(name, "utf-8").decode("unicode_escape") for name in columns]
    if not columns:
        raise ValueError(f"{path} has an empty datasets list")
    tokens = [float(token) for token in FLOAT_RE.findall(data_match.group(1))]
    if len(tokens) % len(columns) != 0:
        raise ValueError(
            f"{path} contains {len(tokens)} numeric values for {len(columns)} datasets; "
            "the row layout is incomplete or unsupported"
        )
    rows = [tokens[i : i + len(columns)] for i in range(0, len(tokens), len(columns))]
    return Table(path=path, format="df-ise-text", columns=columns, rows=rows)


def parse_delimited(path: Path) -> Table:
    sample = path.read_text(encoding="utf-8-sig")
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    try:
        delimiter = csv.Sniffer().sniff(sample[:8192], delimiters=",\t;").delimiter
    except csv.Error:
        pass
    reader = csv.reader(sample.splitlines(), delimiter=delimiter)
    records = list(reader)
    if len(records) < 2:
        raise ValueError(f"{path} needs a header and at least one data row")
    columns = [value.strip() for value in records[0]]
    if len(set(columns)) != len(columns) or any(not value for value in columns):
        raise ValueError(f"{path} has blank or duplicate column names")
    rows: list[list[Any]] = []
    for line_no, record in enumerate(records[1:], start=2):
        if not record or all(not value.strip() for value in record):
            continue
        if len(record) != len(columns):
            raise ValueError(f"{path}:{line_no} has {len(record)} fields; expected {len(columns)}")
        rows.append([value.strip() for value in record])
    if not rows:
        raise ValueError(f"{path} contains no numeric rows")
    return Table(path=path, format="delimited", columns=columns, rows=rows)


def parse_xlsx(path: Path, sheet: str | int | None = None) -> Table:
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("XLSX input requires pandas and openpyxl in the selected Python") from exc
    sheet_name: str | int = 0 if sheet is None else sheet
    frame = pd.read_excel(path, sheet_name=sheet_name)
    if frame.empty:
        raise ValueError(f"{path} contains no data")
    columns = [str(value).strip() for value in frame.columns]
    frame = frame.where(frame.notna(), None)
    return Table(path=path, format="xlsx", columns=columns, rows=frame.values.tolist())


def load_table(path_value: str | Path, sheet: str | int | None = None) -> Table:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix == ".plt":
        return parse_dfise(path)
    if suffix in {".csv", ".tsv", ".txt"}:
        return parse_delimited(path)
    if suffix in {".xlsx", ".xlsm"}:
        return parse_xlsx(path, sheet)
    raise ValueError(f"Unsupported input extension: {suffix}")


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def axis_title_from_column(value: str) -> str:
    value = value.replace("_per_", "/").replace("_", " ")
    return re.sub(r"\s+", " ", value).strip()


def resolve_column(columns: list[str], requested: str) -> str:
    if requested in columns:
        return requested
    lowered = {value.casefold(): value for value in columns}
    if requested.casefold() in lowered:
        return lowered[requested.casefold()]
    normalized = {normalize_name(value): value for value in columns}
    if normalize_name(requested) in normalized:
        return normalized[normalize_name(requested)]
    matches = difflib.get_close_matches(requested, columns, n=5, cutoff=0.35)
    hint = f" Close matches: {', '.join(matches)}" if matches else ""
    raise KeyError(f"Column {requested!r} not found.{hint}")


def first_present(columns: list[str], candidates: Iterable[str]) -> str | None:
    for candidate in candidates:
        try:
            return resolve_column(columns, candidate)
        except KeyError:
            continue
    return None


def preset_matches(table: Table) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for name, preset in PRESETS.items():
        x = first_present(table.columns, preset["x"])
        y = first_present(table.columns, preset["y"])
        if name == "frequency" and x and not y:
            y = next((column for column in table.columns if column != x), None)
        if x and y:
            matches.append({"preset": name, "x": x, "y": y})
    return matches


def numeric_columns(table: Table) -> list[str]:
    numeric: list[str] = []
    for index, column in enumerate(table.columns):
        seen_value = False
        valid = True
        for row in table.rows:
            value = row[index]
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            seen_value = True
            try:
                float(value)
            except (TypeError, ValueError):
                valid = False
                break
        if valid and seen_value:
            numeric.append(column)
    return numeric


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def find_origin_registration() -> dict[str, Any]:
    report: dict[str, Any] = {"registered": False, "progid": None, "executable": None}
    if os.name != "nt":
        return report
    try:
        import winreg
    except ImportError:
        return report

    views = [0, getattr(winreg, "KEY_WOW64_32KEY", 0), getattr(winreg, "KEY_WOW64_64KEY", 0)]
    for progid in ("Origin.ApplicationSI", "Origin.Application"):
        clsid: str | None = None
        for view in views:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CLASSES_ROOT, f"{progid}\\CLSID", 0, winreg.KEY_READ | view
                ) as key:
                    clsid = str(winreg.QueryValueEx(key, "")[0])
                    break
            except OSError:
                continue
        if not clsid:
            continue
        report.update({"registered": True, "progid": progid, "clsid": clsid})
        paths = [f"CLSID\\{clsid}\\LocalServer32", f"WOW6432Node\\CLSID\\{clsid}\\LocalServer32"]
        for subkey in paths:
            for view in views:
                try:
                    with winreg.OpenKey(
                        winreg.HKEY_CLASSES_ROOT, subkey, 0, winreg.KEY_READ | view
                    ) as key:
                        raw = str(winreg.QueryValueEx(key, "")[0]).strip().strip('"')
                    if raw:
                        report["executable"] = raw
                        report["executable_exists"] = Path(raw).is_file()
                        return report
                except OSError:
                    continue
        return report
    return report


def preflight_report() -> dict[str, Any]:
    origin = find_origin_registration()
    originpro_version = package_version("originpro")
    report = {
        "bridge_version": VERSION,
        "platform": platform.platform(),
        "windows": os.name == "nt",
        "python": sys.executable,
        "python_version": platform.python_version(),
        "originpro_version": originpro_version,
        "pandas_version": package_version("pandas"),
        "openpyxl_version": package_version("openpyxl"),
        "origin": origin,
    }
    report["ready"] = bool(report["windows"] and origin["registered"] and originpro_version)
    return report


def origin_process_ids() -> set[int]:
    if os.name != "nt":
        return set()
    try:
        completed = subprocess.run(
            ["tasklist.exe", "/FI", "IMAGENAME eq Origin64.exe", "/FO", "CSV", "/NH"],
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
        )
    except OSError:
        return set()
    pids: set[int] = set()
    for row in csv.reader(completed.stdout.splitlines()):
        if len(row) < 2 or row[0].casefold() != "origin64.exe":
            continue
        try:
            pids.add(int(row[1].replace(",", "")))
        except ValueError:
            continue
    return pids


def wait_for_process_exit(pids: set[int], timeout: float) -> set[int]:
    deadline = time.monotonic() + timeout
    remaining = set(pids)
    while remaining and time.monotonic() < deadline:
        time.sleep(0.25)
        remaining &= origin_process_ids()
    return remaining


def force_close_owned_origin(pids: set[int]) -> set[int]:
    remaining = wait_for_process_exit(pids, 2.0)
    for pid in remaining:
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, PermissionError):
            continue
    return wait_for_process_exit(remaining, 5.0)


def resolve_config_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def transformed_trace(trace: dict[str, Any], base: Path, x_scale: str, y_scale: str) -> dict[str, Any]:
    source = resolve_config_path(str(trace["source"]), base)
    table = load_table(source, trace.get("sheet"))
    x_name = resolve_column(table.columns, str(trace["x"]))
    y_name = resolve_column(table.columns, str(trace["y"]))
    x_factor = float(trace.get("x_factor", 1.0))
    y_factor = float(trace.get("y_factor", 1.0))
    x_offset = float(trace.get("x_offset", 0.0))
    y_offset = float(trace.get("y_offset", 0.0))
    abs_x = bool(trace.get("abs_x", False))
    abs_y = bool(trace.get("abs_y", False))
    x_raw = table.values(x_name)
    y_raw = table.values(y_name)
    pairs: list[tuple[float, float]] = []
    dropped = 0
    for x_value, y_value in zip(x_raw, y_raw):
        x_value = x_value * x_factor + x_offset
        y_value = y_value * y_factor + y_offset
        if abs_x:
            x_value = abs(x_value)
        if abs_y:
            y_value = abs(y_value)
        valid = math.isfinite(x_value) and math.isfinite(y_value)
        if x_scale == "log10" and x_value <= 0:
            valid = False
        if y_scale == "log10" and y_value <= 0:
            valid = False
        if valid:
            pairs.append((x_value, y_value))
        else:
            dropped += 1
    if len(pairs) < 2:
        raise ValueError(f"Trace {trace.get('label', source.stem)!r} has fewer than two valid points")
    return {
        "source": source,
        "source_format": table.format,
        "x_name": x_name,
        "y_name": y_name,
        "x": [pair[0] for pair in pairs],
        "y": [pair[1] for pair in pairs],
        "label": str(trace.get("label") or source.stem),
        "axis": str(trace.get("axis") or "left").lower(),
        "color": str(trace.get("color") or ""),
        "dropped": dropped,
        "x_unit": str(trace.get("x_unit") or ""),
        "y_unit": str(trace.get("y_unit") or ""),
        "transform": {
            "x_factor": x_factor,
            "y_factor": y_factor,
            "x_offset": x_offset,
            "y_offset": y_offset,
            "abs_x": abs_x,
            "abs_y": abs_y,
        },
    }


def validate_config(config_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config.get("traces"), list) or not config["traces"]:
        raise ValueError("Config must contain a non-empty traces list")
    base = config_path.parent
    x_axis = dict(config.get("x_axis") or {})
    y_axis = dict(config.get("y_axis") or {})
    right_y_axis = dict(config.get("right_y_axis") or {})
    layout = str(config.get("layout") or "single-y").lower()
    if layout not in {"single-y", "double-y"}:
        raise ValueError("layout must be 'single-y' or 'double-y'")
    x_scale = str(x_axis.get("scale", "linear"))
    y_scale = str(y_axis.get("scale", "linear"))
    right_y_scale = str(right_y_axis.get("scale", "linear"))
    valid_scales = {"linear", "log10", "ln", "log2"}
    if x_scale not in valid_scales or y_scale not in valid_scales or right_y_scale not in valid_scales:
        raise ValueError(f"Axis scale must be one of {sorted(valid_scales)}")
    raw_traces = config["traces"]
    axes = [str(trace.get("axis") or "left").lower() for trace in raw_traces]
    if any(axis not in {"left", "right"} for axis in axes):
        raise ValueError("Each trace axis must be 'left' or 'right'")
    if layout == "single-y" and any(axis == "right" for axis in axes):
        raise ValueError("single-y layout cannot contain right-axis traces")
    if layout == "double-y" and not ({"left", "right"} <= set(axes)):
        raise ValueError("double-y layout requires at least one left-axis and one right-axis trace")
    traces = [
        transformed_trace(
            trace,
            base,
            x_scale,
            right_y_scale if axis == "right" else y_scale,
        )
        for trace, axis in zip(raw_traces, axes)
    ]
    project = resolve_config_path(str(config["project"]), base)
    if project.suffix.lower() != ".opju":
        raise ValueError("project must use the .opju extension")
    exports = [resolve_config_path(str(value), base) for value in config.get("exports", [])]
    template_output = (
        resolve_config_path(str(config["save_template"]), base) if config.get("save_template") else None
    )
    if template_output and template_output.suffix.lower() != ".otpu":
        raise ValueError("save_template must use the .otpu extension")
    overwrite = bool(config.get("overwrite", False))
    output_paths = [project, *exports, *([template_output] if template_output else [])]
    existing = [str(path) for path in output_paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError("Outputs already exist and overwrite is false: " + ", ".join(existing))
    summary = {
        "project": str(project),
        "exports": [str(path) for path in exports],
        "overwrite": overwrite,
        "layout": layout,
        "style": dict(DEFAULT_FIGURE_STYLE | dict(config.get("style") or {})),
        "x_scale": x_scale,
        "y_scale": y_scale,
        "right_y_scale": right_y_scale if layout == "double-y" else None,
        "traces": [
            {
                "source": str(trace["source"]),
                "x": trace["x_name"],
                "y": trace["y_name"],
                "label": trace["label"],
                "axis": trace["axis"],
                "points": len(trace["x"]),
                "dropped": trace["dropped"],
                "transform": trace["transform"],
            }
            for trace in traces
        ],
    }
    config["_project_path"] = project
    config["_export_paths"] = exports
    config["_template_output_path"] = template_output
    return config, traces, summary


def set_axis_limits(axis: Any, settings: dict[str, Any]) -> None:
    begin = settings.get("from")
    end = settings.get("to")
    step = settings.get("step")
    if begin is not None or end is not None or step is not None:
        axis.set_limits(begin, end, step)


def safe_legend_label(value: str) -> str:
    value = re.sub(r"[\r\n\t]+", " ", value).strip()
    value = value.replace("\\", "/").replace('"', "'").replace(";", ",")
    return value.replace("%", "percent")


def safe_labtalk_text(value: str) -> str:
    value = re.sub(r"[\r\n\t]+", " ", value).strip()
    return value.replace('"', "'").replace(";", ",")


def styled_text(value: str, bold: bool) -> str:
    value = safe_labtalk_text(value)
    return f"\\b({value})" if bold else value


def publication_style(config: dict[str, Any]) -> dict[str, Any]:
    style = dict(DEFAULT_FIGURE_STYLE)
    style.update(dict(config.get("style") or {}))
    font = str(style["font"])
    if not re.fullmatch(r"[A-Za-z0-9 _-]+", font):
        raise ValueError("style.font contains unsupported characters")
    style["font_size"] = float(style["font_size"])
    style["axis_thickness"] = float(style["axis_thickness"])
    style["data_line_width"] = float(style["data_line_width"])
    style["major_ticks"] = int(style["major_ticks"])
    style["page_width"] = int(style["page_width"])
    style["page_height"] = int(style["page_height"])
    style["page_dpi"] = int(style["page_dpi"])
    style["page_orientation"] = int(style["page_orientation"])
    style["page_update_to_printer"] = int(style["page_update_to_printer"])
    if min(
        style["font_size"],
        style["axis_thickness"],
        style["data_line_width"],
        style["page_width"],
        style["page_height"],
        style["page_dpi"],
    ) <= 0:
        raise ValueError("Style sizes, line widths, page dimensions, and DPI must be positive")
    if style["major_ticks"] < 2:
        raise ValueError("style.major_ticks must be at least 2")
    if style["page_orientation"] not in {1, 2}:
        raise ValueError("style.page_orientation must be 1 (portrait) or 2 (landscape)")
    if style["page_update_to_printer"] not in {0, 1, 2}:
        raise ValueError("style.page_update_to_printer must be 0, 1, or 2")
    style["scientific_format"] = str(style["scientific_format"]).lower()
    if style["scientific_format"] not in {"power", "e"}:
        raise ValueError("style.scientific_format must be 'power' or 'E'")
    style["bold"] = bool(style["bold"])
    style["legend_border"] = bool(style["legend_border"])
    return style


def apply_page_style(op: Any, style: dict[str, Any]) -> None:
    log_one_as_power = 0 if style["scientific_format"] == "power" else 1
    max_numeric_ticks = max(12, int(style["major_ticks"]))
    op.lt_exec(
        "page.unit=3;"
        f"page.resx={style['page_dpi']};"
        f"page.resy={style['page_dpi']};"
        f"page.width={style['page_width']};"
        f"page.height={style['page_height']};"
        f"page.orientation={style['page_orientation']};"
        f"page.updatetoprinter={style['page_update_to_printer']};"
        "page.viewmode=2;"
        f"system.tick.log1As10E={log_one_as_power};"
        f"system.tick.maxNumeric={max_numeric_ticks};"
    )


def axis_needs_scientific(settings: dict[str, Any], axis: Any) -> bool:
    requested = str(settings.get("number_format", "auto")).lower()
    if requested in {"power", "scientific", "10^x"}:
        return True
    if requested in {"decimal", "plain"}:
        return False
    if requested != "auto":
        raise ValueError("Axis number_format must be auto, decimal, or power")
    scale = str(settings.get("scale", "linear")).lower()
    if scale in {"log10", "ln", "log2"}:
        return True
    magnitudes: list[float] = []
    for value in (axis.sfrom, axis.sto):
        number = abs(float(value))
        if math.isfinite(number) and number > 0:
            magnitudes.append(number)
    return bool(magnitudes) and (max(magnitudes) >= 1e4 or min(magnitudes) <= 1e-3)


def apply_axis_presentation(
    op: Any,
    layer_index: int,
    axis_names: Iterable[str],
    settings: dict[str, Any],
    axis: Any,
    style: dict[str, Any],
) -> None:
    op.lt_exec(f"page.active={layer_index};")
    major_ticks = int(settings.get("major_ticks", style["major_ticks"]))
    if major_ticks < 2:
        raise ValueError("Axis major_ticks must be at least 2")
    use_tick_count = settings.get("step") is None
    number_format = 2 if axis_needs_scientific(settings, axis) else 1
    commands: list[str] = []
    for axis_name in axis_names:
        if use_tick_count:
            commands.append(f"layer.{axis_name}.majorTicks={major_ticks}")
        commands.extend(
            [
                f"layer.{axis_name}.label.numFormat={number_format}",
                f"layer.{axis_name}.labelSubtype={number_format}",
            ]
        )
    op.lt_exec(";".join(commands) + ";")


def apply_layer_style(op: Any, layer_index: int, style: dict[str, Any], axes: Iterable[str]) -> None:
    op.lt_exec(f"page.active={layer_index};")
    font = style["font"]
    font_size = style["font_size"]
    thickness = style["axis_thickness"]
    bold = 1 if style["bold"] else 0
    commands: list[str] = []
    for axis in axes:
        commands.extend(
            [
                f"layer.{axis}.thickness={thickness}",
                f"layer.{axis}.tickthickness={thickness}",
                f"layer.{axis}.mtickthickness={thickness}",
                f"layer.{axis}.label.font=font({font})",
                f"layer.{axis}.label.pt={font_size}",
                f"layer.{axis}.label.bold={bold}",
            ]
        )
    op.lt_exec(";".join(commands) + ";")


def apply_layer_geometry(op: Any, layer_index: int, layout: str) -> None:
    geometry = FIGURE_GEOMETRY[layout]
    op.lt_exec(f"page.active={layer_index};")
    op.lt_exec(
        "layer.unit=1;"
        f"layer.left={geometry['left']};"
        f"layer.top={geometry['top']};"
        f"layer.width={geometry['width']};"
        f"layer.height={geometry['height']};"
    )


def style_axis_title(op: Any, layer_index: int, object_name: str, style: dict[str, Any]) -> None:
    op.lt_exec(f"page.active={layer_index};")
    op.lt_exec(
        f"{object_name}.font=font({style['font']});"
        f"{object_name}.fsize={style['font_size']};"
    )


def save_graph_template(op: Any, graph: Any, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    graph.activate()
    template_name = safe_labtalk_text(output.stem)
    template_dir = safe_labtalk_text(str(output.parent))
    op.lt_exec(
        f'template_saveas template:="{template_name}" filepath:="{template_dir}" '
        'ftype:=0 emf:=0 bmp:=0 loadsys:=0 asksave:=0;'
    )
    if not output.is_file():
        raise RuntimeError(f"Origin failed to save graph template to {output}")
    return output


def create_origin_outputs(
    config: dict[str, Any], traces: list[dict[str, Any]], keep_open_override: bool
) -> dict[str, Any]:
    try:
        import originpro as op
    except ImportError as exc:
        raise RuntimeError("originpro is not installed in the selected Python interpreter") from exc

    project: Path = config["_project_path"]
    exports: list[Path] = config["_export_paths"]
    template_output: Path | None = config.get("_template_output_path")
    overwrite = bool(config.get("overwrite", False))
    visible = bool(config.get("visible", True))
    keep_open = keep_open_override or bool(config.get("keep_open", False))
    force_close = bool(config.get("force_close_owned_origin", True))
    layout = str(config.get("layout") or "single-y").lower()
    style = publication_style(config)
    origin_pids_before = origin_process_ids()
    owned_origin_pids: set[int] = set()
    project.parent.mkdir(parents=True, exist_ok=True)
    for export in exports:
        export.parent.mkdir(parents=True, exist_ok=True)
    if template_output:
        template_output.parent.mkdir(parents=True, exist_ok=True)

    started = False
    created_exports: list[str] = []
    created_template = ""
    worksheet = None
    graph = None
    left_layer = None
    right_layer = None
    plot = None
    x_axis = None
    y_axis = None
    right_x_axis = None
    right_y_axis = None
    right_title_axis = None
    try:
        if op.oext:
            op.set_show(visible)
        op.new(asksave=False)
        started = True
        owned_origin_pids = origin_process_ids() - origin_pids_before

        worksheet = op.new_sheet("w", str(config.get("workbook_name", "TCAD Data")))
        worksheet.cols = 2 * len(traces)
        for index, trace in enumerate(traces):
            x_col = 2 * index
            y_col = x_col + 1
            worksheet.from_list(
                x_col,
                trace["x"],
                lname=f"{trace['label']} — {trace['x_name']}",
                units=trace["x_unit"],
                comments=f"Source: {trace['source']}",
                axis="X",
            )
            worksheet.from_list(
                y_col,
                trace["y"],
                lname=trace["label"],
                units=trace["y_unit"],
                comments="",
                axis="Y",
            )

        template = str(config.get("template") or "")
        graph = op.new_graph(
            lname=str(config.get("graph_name", "Sentaurus TCAD")),
            template=template,
            hidden=not visible,
        )
        if graph is None:
            raise RuntimeError(f"Origin could not create a graph from template {template!r}")
        left_layer = graph[0]
        if layout == "double-y":
            try:
                right_layer = graph[1]
            except Exception:
                right_layer = graph.add_layer(2)
            if right_layer is None:
                raise RuntimeError("Origin could not create the right-Y graph layer")

        plot_type = str(config.get("plot_type", "l"))
        layer_plot_counts = {1: 0, 2: 0}
        legend_entries: list[tuple[int, int, dict[str, Any]]] = []
        for index, trace in enumerate(traces):
            layer_index = 2 if trace["axis"] == "right" else 1
            target_layer = right_layer if layer_index == 2 else left_layer
            if target_layer is None:
                raise RuntimeError(f"Trace {trace['label']!r} targets a missing graph layer")
            plot = target_layer.add_plot(
                worksheet,
                coly=2 * index + 1,
                colx=2 * index,
                type=plot_type,
            )
            plot.color = trace["color"] or COLORBLIND_SAFE[index % len(COLORBLIND_SAFE)]
            plot.set_float("line.width", style["data_line_width"])
            layer_plot_counts[layer_index] += 1
            legend_entries.append((layer_index, layer_plot_counts[layer_index], trace))

        x_axis_settings = dict(config.get("x_axis") or {})
        y_axis_settings = dict(config.get("y_axis") or {})
        right_y_axis_settings = dict(config.get("right_y_axis") or {})
        left_layer.xscale = str(x_axis_settings.get("scale", "linear"))
        left_layer.yscale = str(y_axis_settings.get("scale", "linear"))
        left_layer.rescale()
        x_axis = left_layer.axis("x")
        y_axis = left_layer.axis("y")
        x_axis.title = styled_text(
            str(x_axis_settings.get("title", traces[0]["x_name"])), style["bold"]
        )
        left_fallback = next(trace["y_name"] for trace in traces if trace["axis"] == "left")
        y_axis.title = styled_text(
            str(y_axis_settings.get("title", left_fallback)), style["bold"]
        )
        set_axis_limits(x_axis, x_axis_settings)
        set_axis_limits(y_axis, y_axis_settings)

        if layout == "double-y" and right_layer is not None:
            right_layer.xscale = str(x_axis_settings.get("scale", "linear"))
            right_layer.yscale = str(right_y_axis_settings.get("scale", "linear"))
            right_layer.rescale()
            right_x_axis = right_layer.axis("x")
            right_y_axis = right_layer.axis("y")
            right_title_axis = right_layer.axis("y2")
            right_fallback = next(trace["y_name"] for trace in traces if trace["axis"] == "right")
            right_title_axis.title = styled_text(
                str(right_y_axis_settings.get("title", right_fallback)), style["bold"]
            )
            set_axis_limits(right_y_axis, right_y_axis_settings)
            if any(key in x_axis_settings for key in ("from", "to", "step")):
                set_axis_limits(right_x_axis, x_axis_settings)
            else:
                right_x_axis.set_limits(x_axis.sfrom, x_axis.sto, x_axis.sstep)

        graph.activate()
        apply_page_style(op, style)
        apply_layer_geometry(op, 1, layout)
        apply_layer_style(op, 1, style, ("x", "y"))
        apply_axis_presentation(op, 1, ("x",), x_axis_settings, x_axis, style)
        apply_axis_presentation(op, 1, ("y",), y_axis_settings, y_axis, style)
        style_axis_title(op, 1, "xb", style)
        style_axis_title(op, 1, "yl", style)
        if layout == "double-y":
            apply_layer_geometry(op, 2, layout)
            apply_layer_style(op, 2, style, ("x", "y", "y2"))
            apply_axis_presentation(op, 2, ("x",), x_axis_settings, right_x_axis, style)
            apply_axis_presentation(
                op,
                2,
                ("y", "y2"),
                right_y_axis_settings,
                right_y_axis,
                style,
            )
            style_axis_title(op, 2, "yr", style)
        op.lt_exec("page.active=1;")
        legend_lines = [
            f"\\l({layer_index}.{plot_index}) "
            f"{styled_text(safe_legend_label(trace['label']), style['bold'])}"
            for layer_index, plot_index, trace in legend_entries
        ]
        legend_text = "%(CRLF)".join(legend_lines)
        op.lt_exec("label -r legend;")
        op.lt_exec(f'label -p 2 2 -sl -n legend "{legend_text}";')
        legend_background = 1 if style["legend_border"] else 0
        op.lt_exec(
            f"legend.font=font({style['font']});"
            f"legend.fsize={style['font_size']};"
            f"legend.background={legend_background};"
            "doc -uw;"
        )

        if template_output:
            created_template = str(save_graph_template(op, graph, template_output))

        width = int(config.get("raster_width", 2400))
        vector_ratio = int(config.get("vector_ratio", 100))
        for export in exports:
            extension = export.suffix.lower().lstrip(".")
            if not extension:
                raise ValueError(f"Export path needs an extension: {export}")
            kwargs: dict[str, Any] = {"replace": overwrite}
            if extension in {"png", "jpg", "jpeg", "bmp", "tif", "tiff"}:
                kwargs["width"] = width
            else:
                kwargs["ratio"] = vector_ratio
            generated = graph.save_fig(str(export), type=extension, **kwargs)
            generated_path = Path(generated).resolve() if generated else export
            if not generated_path.is_file() and not export.is_file():
                raise RuntimeError(f"Origin failed to export {export}")
            created_exports.append(str(generated_path if generated_path.is_file() else export))

        # Export operations can update graph export settings and mark the project modified.
        # Save last so the automated instance can close without an invisible save prompt.
        if not op.save(str(project)) or not project.is_file():
            raise RuntimeError(f"Origin did not save the project to {project}")

        return {
            "project": str(project),
            "exports": created_exports,
            "template": created_template,
            "origin_left_open": keep_open,
            "trace_count": len(traces),
            "layout": layout,
        }
    finally:
        if started and op.oext and not keep_open:
            # OriginExt keeps the server alive while wrapper objects still hold COM proxies.
            # Release every local wrapper before asking the automation-owned instance to exit.
            y_axis = None
            x_axis = None
            right_y_axis = None
            right_x_axis = None
            right_title_axis = None
            plot = None
            right_layer = None
            left_layer = None
            graph = None
            worksheet = None
            gc.collect()
            try:
                # Discard any residual modified state in the automation-owned instance.
                op.new(asksave=False)
            except Exception:
                pass
            op.exit()
            gc.collect()
            remaining = wait_for_process_exit(owned_origin_pids, 2.0)
            if remaining and force_close:
                remaining = force_close_owned_origin(remaining)
            if remaining:
                raise RuntimeError(
                    "Automation-owned Origin process did not exit: "
                    + ", ".join(str(pid) for pid in sorted(remaining))
                )


def command_preflight(args: argparse.Namespace) -> int:
    report = preflight_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] or not args.require_ready else 2


def command_inspect(args: argparse.Namespace) -> int:
    table = load_table(args.input, args.sheet)
    report = {
        "path": str(table.path),
        "format": table.format,
        "rows": table.row_count,
        "columns": table.columns,
        "numeric_columns": numeric_columns(table),
        "preset_matches": preset_matches(table),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def default_project_filename(config_path: Path, project_name: str | None) -> str:
    if project_name:
        candidate = Path(project_name)
        if candidate.is_absolute() or candidate.name != project_name:
            raise ValueError("--project-name must be a filename, not a path")
        if candidate.suffix and candidate.suffix.lower() != ".opju":
            raise ValueError("--project-name must use the .opju extension")
        return candidate.name if candidate.suffix else candidate.name + ".opju"

    stem = config_path.stem
    if stem.lower().endswith(".origin"):
        stem = stem[: -len(".origin")]
    return (stem or "origin-project") + ".opju"


def routed_project_path(
    config_path: Path,
    output_root_value: str,
    dependent_project_value: str | None,
    project_name: str | None,
) -> Path:
    output_root = Path(output_root_value).expanduser().resolve()
    folder_name = DEFAULT_TEMP_PROJECT_FOLDER
    if dependent_project_value:
        dependent_project = Path(dependent_project_value).expanduser().resolve()
        if not dependent_project.is_dir():
            raise NotADirectoryError(
                f"Dependent project folder does not exist or is not a directory: {dependent_project}"
            )
        if not dependent_project.name:
            raise ValueError("Dependent project must be a named folder, not a drive root")
        folder_name = dependent_project.name
    return output_root / folder_name / default_project_filename(config_path, project_name)


def command_make_config(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser().resolve()
    if config_path.exists() and not args.force:
        raise FileExistsError(f"Config exists; use --force to replace it: {config_path}")
    preset = PRESETS.get(args.preset, {})
    right_y_traces = set(args.right_y_trace or [])
    invalid_right_indices = sorted(index for index in right_y_traces if index < 1 or index > len(args.input))
    if invalid_right_indices:
        raise ValueError(f"--right-y-trace indices are out of range: {invalid_right_indices}")
    if args.figure_template == "single-y" and right_y_traces:
        raise ValueError("single-y template cannot use --right-y-trace")
    if args.figure_template == "double-y" and len(args.input) < 2:
        raise ValueError("double-y template requires at least two input traces")
    if args.figure_template == "double-y" and not right_y_traces:
        right_y_traces.add(len(args.input))

    traces: list[dict[str, Any]] = []
    for index, source_value in enumerate(args.input):
        table = load_table(source_value, args.sheet)
        is_right_y = index + 1 in right_y_traces
        if args.x:
            x_name = resolve_column(table.columns, args.x)
        else:
            x_name = first_present(table.columns, preset.get("x", []))
        if is_right_y and args.right_y:
            y_name = resolve_column(table.columns, args.right_y)
        elif args.y:
            y_name = resolve_column(table.columns, args.y)
        else:
            y_name = first_present(table.columns, preset.get("y", []))
            if args.preset == "frequency" and x_name and not y_name:
                y_name = next((column for column in table.columns if column != x_name), None)
        if not x_name or not y_name:
            raise KeyError(f"Could not infer X/Y for {table.path}; run inspect and pass --x/--y")
        label = args.label[index] if args.label and index < len(args.label) else table.path.stem
        traces.append(
            {
                "source": str(table.path),
                "x": x_name,
                "y": y_name,
                "label": label,
                "axis": "right" if is_right_y else "left",
                "x_factor": args.x_factor,
                "y_factor": (
                    args.right_y_factor
                    if is_right_y and args.right_y_factor is not None
                    else args.y_factor
                ),
                "abs_y": bool(args.right_y_abs) if is_right_y else bool(preset.get("abs_y", False)),
            }
        )

    project = (
        Path(args.project).expanduser().resolve()
        if args.project
        else routed_project_path(
            config_path,
            args.output_root,
            args.dependent_project,
            args.project_name,
        )
    )
    exports = [str(Path(value).expanduser().resolve()) for value in args.export]
    bundled_template = FIGURE_TEMPLATES[args.figure_template]
    if not args.template and not bundled_template.is_file():
        raise FileNotFoundError(f"Bundled Origin template is missing: {bundled_template}")
    template = Path(args.template).expanduser().resolve() if args.template else bundled_template.resolve()
    right_trace = next((trace for trace in traces if trace["axis"] == "right"), None)
    config = {
        "project": str(project),
        "exports": exports,
        "overwrite": False,
        "visible": True,
        "keep_open": False,
        "force_close_owned_origin": True,
        "graph_name": args.graph_name or args.preset.upper(),
        "workbook_name": "TCAD Data",
        "figure_template": args.figure_template,
        "layout": args.figure_template,
        "template": str(template),
        "save_template": (
            str(Path(args.save_template).expanduser().resolve()) if args.save_template else ""
        ),
        "style": dict(DEFAULT_FIGURE_STYLE),
        "plot_type": "l",
        "raster_width": 2400,
        "vector_ratio": 100,
        "x_axis": {
            "title": args.x_title or preset.get("x_title", x_name),
            "scale": args.x_scale or preset.get("x_scale", "linear"),
        },
        "y_axis": {
            "title": args.y_title or preset.get("y_title") or axis_title_from_column(y_name),
            "scale": args.y_scale or preset.get("y_scale", "linear"),
        },
        "right_y_axis": {
            "title": args.right_y_title
            or (axis_title_from_column(right_trace["y"]) if right_trace else "Right Y"),
            "scale": args.right_y_scale or "linear",
        },
        "traces": traces,
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(config_path)
    return 0


def command_plot(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser().resolve()
    config, traces, summary = validate_config(config_path)
    if args.dry_run:
        summary["dry_run"] = True
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    preflight = preflight_report()
    if not preflight["ready"]:
        raise RuntimeError("Origin automation preflight is not ready: " + json.dumps(preflight, ensure_ascii=False))
    result = create_origin_outputs(config, traces, args.keep_open)
    result["dry_run"] = False
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight", help="Check Python and Origin automation readiness")
    preflight.add_argument("--require-ready", action="store_true")
    preflight.set_defaults(handler=command_preflight)

    inspect_cmd = subparsers.add_parser("inspect", help="Inspect supported source columns without Origin")
    inspect_cmd.add_argument("input")
    inspect_cmd.add_argument("--sheet")
    inspect_cmd.set_defaults(handler=command_inspect)

    make_config = subparsers.add_parser("make-config", help="Create a conservative plotting config")
    make_config.add_argument("--preset", choices=[*PRESETS, "custom"], required=True)
    make_config.add_argument("--input", nargs="+", required=True)
    make_config.add_argument("--config", required=True)
    make_config.add_argument(
        "--project",
        help="Explicit .opju target; overrides automatic OriginPlot routing",
    )
    make_config.add_argument(
        "--dependent-project",
        help="Project root whose folder name becomes the OriginPlot output subfolder",
    )
    make_config.add_argument(
        "--output-root",
        default=str(DEFAULT_ORIGIN_OUTPUT_ROOT),
        help=f"Automatic Origin project root (default: {DEFAULT_ORIGIN_OUTPUT_ROOT})",
    )
    make_config.add_argument(
        "--project-name",
        help="Automatic-route .opju filename; defaults to the config filename stem",
    )
    make_config.add_argument("--export", nargs="*", default=[])
    make_config.add_argument("--x")
    make_config.add_argument("--y")
    make_config.add_argument("--right-y")
    make_config.add_argument("--right-y-abs", action="store_true")
    make_config.add_argument("--label", nargs="*")
    make_config.add_argument("--sheet")
    make_config.add_argument("--template")
    make_config.add_argument("--save-template")
    make_config.add_argument(
        "--figure-template",
        choices=sorted(FIGURE_TEMPLATES),
        default="single-y",
        help="Bundled Arial 30 bold single- or double-Y Origin template",
    )
    make_config.add_argument(
        "--right-y-trace",
        nargs="*",
        type=int,
        help="1-based trace indices for the right Y axis; double-y defaults to the last trace",
    )
    make_config.add_argument("--graph-name")
    make_config.add_argument("--x-title")
    make_config.add_argument("--y-title")
    make_config.add_argument("--x-scale", choices=["linear", "log10", "ln", "log2"])
    make_config.add_argument("--y-scale", choices=["linear", "log10", "ln", "log2"])
    make_config.add_argument("--right-y-title")
    make_config.add_argument("--right-y-scale", choices=["linear", "log10", "ln", "log2"])
    make_config.add_argument("--x-factor", type=float, default=1.0)
    make_config.add_argument("--y-factor", type=float, default=1.0)
    make_config.add_argument("--right-y-factor", type=float)
    make_config.add_argument("--force", action="store_true")
    make_config.set_defaults(handler=command_make_config)

    plot = subparsers.add_parser("plot", help="Validate a config or create Origin outputs")
    plot.add_argument("config")
    plot.add_argument("--dry-run", action="store_true")
    plot.add_argument("--keep-open", action="store_true")
    plot.set_defaults(handler=command_plot)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
