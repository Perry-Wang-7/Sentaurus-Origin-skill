# Configuration and presets

## Contents

- Path resolution
- Full configuration example
- Trace transforms
- Axis and export settings
- Bundled figure templates
- Preset semantics
- Multi-trace guidance

## Path resolution

The bridge resolves relative paths in a plotting JSON file relative to the JSON file's directory. `make-config` writes absolute paths by default. Prefer absolute paths when data and output live on different drives.

When `make-config` is called without `--project`, it routes the `.opju` beneath `E:\Pictures\OriginPlot`:

- `--dependent-project "D:\path\ProjectName"` produces `E:\Pictures\OriginPlot\ProjectName\<project-name>.opju`.
- Omitting `--dependent-project` produces `E:\Pictures\OriginPlot\Origin-Temp\<project-name>.opju`.
- `--project-name` sets the filename. Without it, the bridge derives the filename from the config name and removes a trailing `.origin` stem, so `idvg.origin.json` becomes `idvg.opju`.
- `--project` remains an explicit override and bypasses automatic routing.

Pass the real project root, not an intermediate `output`, `raw`, `results`, or node directory. If the project root is unknown, use the `Origin-Temp` fallback instead of guessing. The project output directory is created only when `plot` writes the Origin project.

The bridge refuses to replace an existing `.opju` or export while `overwrite` is false. Set `overwrite` to true only after confirming the exact targets.

With `keep_open` false, `force_close_owned_origin` cleans up only the new Origin PID detected after this bridge starts. It never targets Origin processes that existed before the run. Set it to false only for debugging an Origin shutdown problem.

## Full configuration example

```json
{
  "project": "E:/Pictures/OriginPlot/my-device-project/idvg_compare.opju",
  "exports": [
    "D:/results/idvg_compare.png",
    "D:/results/idvg_compare.svg"
  ],
  "overwrite": false,
  "visible": true,
  "keep_open": false,
  "force_close_owned_origin": true,
  "graph_name": "Id-Vg comparison",
  "workbook_name": "TCAD Data",
  "layout": "single-y",
  "figure_template": "single-y",
  "template": "<skill-dir>/assets/origin-single-y-arial30.otpu",
  "save_template": null,
  "style": {
    "font": "Arial",
    "font_size": 30,
    "bold": true,
    "axis_thickness": 4,
    "data_line_width": 4,
    "legend_border": false,
    "major_ticks": 7,
    "scientific_format": "power",
    "page_width": 6432,
    "page_height": 4923,
    "page_dpi": 600,
    "page_orientation": 2,
    "page_update_to_printer": 1
  },
  "plot_type": "l",
  "raster_width": 2400,
  "vector_ratio": 100,
  "x_axis": {
    "title": "V\\-(G) (V)",
    "scale": "linear",
    "major_ticks": 7,
    "number_format": "decimal",
    "from": -6,
    "to": 2,
    "step": 1
  },
  "y_axis": {
    "title": "|I\\-(D)| (mA/mm)",
    "scale": "log10",
    "major_ticks": 7,
    "number_format": "power",
    "from": 1e-8,
    "to": 1e3
  },
  "traces": [
    {
      "source": "D:/results/n321_des.plt",
      "axis": "left",
      "x": "gate OuterVoltage",
      "y": "drain TotalCurrent",
      "label": "Baseline",
      "x_factor": 1.0,
      "y_factor": 1000.0,
      "x_offset": 0.0,
      "y_offset": 0.0,
      "abs_x": false,
      "abs_y": true,
      "x_unit": "V",
      "y_unit": "mA/mm",
      "color": "#0072B2"
    }
  ]
}
```

## Trace transforms

For each numeric value, the bridge applies operations in this order:

1. `value * factor + offset`
2. optional absolute value
3. finite-value filtering
4. positive-value filtering for a logarithmic axis

Set `y_factor` only from an explicit unit conversion or geometry normalization. Examples:

- A to mA: `y_factor = 1000`
- total current to A/mm for a simulated width of `W_um`: `y_factor = 1000 / W_um`
- capacitance F/mm to fF/mm: `y_factor = 1e15`

Do not infer the simulated width from a plot label or filename. Read it from the deck, parameter table, or result metadata.

## Axis and export settings

Supported scale strings are `linear`, `log10`, `ln`, and `log2`. Optional `from`, `to`, and `step` values are applied after Origin rescales the plotted data.

Use `major_ticks` to request an approximate count of major ticks. The bundled style defaults to seven on every visible axis so horizontal, left-Y, and right-Y scales have similar density. An explicit `step` takes precedence over the count.

Use axis `number_format` values `auto`, `decimal`, or `power`. `auto` uses `10^x` on logarithmic axes and on very small or large linear ranges, while keeping ordinary linear values decimal. `power` forces the powers-of-ten form; `decimal` prevents scientific formatting.

`raster_width` controls pixel width for PNG, TIFF, JPEG, and BMP exports. Choose width from final print size; for example, 8 inches at 300 dpi requires at least 2400 pixels.

`vector_ratio` controls Origin's vector export size factor. The extension in each export path selects the format.

Use a full `.otp` or `.otpu` template path for repeatable page size, font, line width, symbols, layer layout, and journal styling. If no template is supplied, the bridge creates a normal line graph and sets axis titles, scales, colors, and data provenance.

## Bundled figure templates

`make-config --figure-template single-y` selects `assets/origin-single-y-arial30.otpu`. `make-config --figure-template double-y` selects `assets/origin-double-y-arial30.otpu`. Both enforce:

- Arial, 30 pt, bold text for tick labels, axis titles, and legend.
- Axis, tick, and data-line thickness of 4 pt.
- Borderless legend.
- Approximately seven major ticks per visible axis unless an explicit increment is supplied.
- Powers-of-ten scientific notation (`10^x`) instead of `1E±x` whenever scientific notation is needed.
- A nominal 6432 × 4923 dot, 600 dpi landscape page with printer-aware template loading; Origin may adjust the saved page width to the active printer while preserving the aspect and margins.

The single-Y layout puts every trace on the left Y axis. The double-Y layout uses two linked Origin layers: left-axis traces are in layer 1 and right-axis traces are in layer 2. Each trace has `"axis": "left"` or `"axis": "right"`; the config must contain at least one of each. `right_y_axis` accepts the same `title`, `scale`, `from`, `to`, and `step` fields as `y_axis`.

For `make-config`, `--right-y-trace` takes 1-based trace numbers. If it is omitted for a double-Y plot, the last trace goes to the right axis. `--right-y` can give the right-side traces a different source column; `--right-y-abs`, `--right-y-factor`, `--right-y-title`, and `--right-y-scale` control its transform and axis.

Set `save_template` in JSON, or pass `--save-template <path.otpu>`, to save the completed graph as an additional reusable Origin graph template. This is separate from the editable `.opju` project and figure exports.

## RFSW-derived print style

The supplied RFSW Origin project contains 172 graph pages. A representative 12-page audit found a consistent house style: 6432 × 4923 dots at 600 dpi, landscape orientation, a plot layer near 18% left / 12% top / 68% width / 72% height, 4 pt axes and curves, bold sans-serif labels, borderless legends, and restrained black/red/blue emphasis. Axis variables often use italic symbols and true subscripts.

Adopt the stable structural choices—page proportions, margins, heavy axes and curves, borderless legend, and compact scientific notation—but keep the user's requested Arial 30 pt instead of the reference project's usual 22 pt. Use italics and subscripts only when the physical notation calls for them. Do not copy page-specific annotations or overlapping multi-layer layouts from the reference project.

## Preset semantics

### `idvg`

- Plot gate voltage against drain total current.
- Apply absolute value to current and use log10 Y by default.
- Use raw amperes unless width normalization is provided.
- Inspect low-current points removed by the log filter; zeros and non-finite values are reported as dropped.

### `idvd`

- Plot drain voltage against drain total current.
- Preserve current sign and use linear Y by default.
- Sort traces physically by gate bias if comparing a family of curves; encode the gate bias in each label.

### `bv`

- Prefer drain InnerVoltage when it represents the actual device voltage; otherwise use OuterVoltage and document the choice.
- Apply absolute value and log10 current by default.
- Do not claim breakdown voltage solely from the axis end point; apply the project's defined current criterion.

### `transient`

- Plot `time` against the selected response.
- Preserve signed current unless the scientific question explicitly uses magnitude.
- For HeavyIon/SEB, retain the raw time base and document any normalization or baseline subtraction.

### `frequency`

- Select the detected frequency column and the requested response.
- Derive the default Y-axis title from the actual response column; revise it to journal notation when needed.
- The preset defaults to log10 frequency because sweep points are commonly logarithmic; change to linear when scientifically appropriate.

### `custom`

Run `inspect`, then pass exact `--x` and `--y` names to `make-config`.

## Multi-trace guidance

- Keep each trace as its own X/Y column pair so different grids and lengths remain editable in Origin.
- Use labels that expose the swept physical parameter, not only node numbers.
- Keep source path, original column name, and transform in the workbook metadata and dry-run report.
- If sources use different units, normalize them before plotting and make the common unit explicit in the axis title.
- When combining Id-Vg curves from different drain biases, order them monotonically by drain bias.
