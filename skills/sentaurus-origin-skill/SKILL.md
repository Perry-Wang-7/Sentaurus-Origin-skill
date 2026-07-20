---
name: sentaurus-origin-skill
description: Automate editable Origin/OriginPro plots and publication figure exports from Sentaurus TCAD results. Use when a user asks to link Codex, Sentaurus, and Origin; inspect or plot DF-ISE text .plt, CSV, TSV, or XLSX data in Origin; create or update .opju projects; apply Origin .otp/.otpu templates; use the bundled print-ready single-Y or double-Y publication templates; balance axis tick density; format scientific ticks as 10^x; batch Id-Vg, Id-Vd, breakdown, transient, or frequency plots; or export Origin graphs to PNG, TIFF, SVG, PDF, EPS, or EMF.
---

# Sentaurus-Origin plotting

Use the bundled bridge to turn validated Sentaurus curve data into a new, editable Origin project and exported figures. Keep Sentaurus Visual responsible for `.tdr` spatial fields; use Origin for XY curves, comparison plots, fitting, and final layout.

## Safety and evidence rules

1. Confirm the simulation completed before treating a curve as scientific evidence. Check the relevant SDevice log for `Good Bye`, `FATAL`, or `Step-size is too small`.
2. Never infer `.tdr` spatial mechanisms from an Origin XY plot. Open the `.tdr` in Sentaurus Visual for field, carrier, temperature, avalanche, or heavy-ion distributions.
3. Treat Sentaurus `.plt` as DF-ISE data, not as an Origin plot file. Parse it only when it begins with `DF-ISE text`; otherwise export it through a verified Sentaurus tool first.
4. Create a new Origin automation instance by default. Do not attach to or overwrite a user's open Origin project.
5. Keep `overwrite` false unless the user explicitly authorizes replacing named outputs. Prefer a new output directory or timestamped filenames.
6. Run a dry validation before launching Origin. Launching Origin is a visible desktop action and may require approval.

## Resolve the runner

Resolve `<skill-dir>` from the directory containing this `SKILL.md`; never hard-code a user profile. On Windows invoke:

```powershell
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run-origin-bridge.ps1" <command> <arguments>
```

The wrapper prefers `SENTAURUS_ORIGIN_PYTHON`, then the bundled Codex Python, `py -3`, and `python`.

## Route Origin projects

Store every newly generated `.opju` under `E:\Pictures\OriginPlot`:

- When the task depends on a known project folder, create or select `E:\Pictures\OriginPlot\<project-folder-name>` and save the `.opju` there. Pass the exact project root with `--dependent-project`; use only its final folder name for the output subfolder.
- When no dependent project is known, save the `.opju` under `E:\Pictures\OriginPlot\Origin-Temp` by omitting `--dependent-project`.
- Do not infer a project root from intermediate data directories such as `output`, `raw`, `results`, or a node folder. If the actual project root cannot be established from task context, use `Origin-Temp`.
- Omit `--project` to use this routing. Use an explicit `--project` only when the user asks for a different path.
- Keep `overwrite` false. Reuse neither a project directory nor a filename as permission to replace an existing `.opju`; choose a versioned or timestamped filename instead.

The bridge creates the routed folder when Origin writes the project. `make-config` only records the resolved target during configuration.

## Workflow

### 1. Preflight

Run:

```powershell
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run-origin-bridge.ps1" preflight
```

Require Windows, an Origin Automation COM registration, and the external `originpro` package. If `originpro` is missing, explain that it is OriginLab's external Python API and request permission before installing it into the selected interpreter. Re-run preflight after installation.

### 2. Inspect source data

Inspect every distinct input schema before choosing columns:

```powershell
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run-origin-bridge.ps1" inspect "path\to\n123_des.plt"
```

Use exact column names reported by `inspect`. For common simulations prefer:

| Preset | X | Y | Default Y scale |
|---|---|---|---|
| `idvg` | `gate OuterVoltage` | `drain TotalCurrent` | log10 of absolute current |
| `idvd` | `drain OuterVoltage` | `drain TotalCurrent` | linear |
| `bv` | `drain InnerVoltage` or `drain OuterVoltage` | `drain TotalCurrent` | log10 of absolute current |
| `transient` | `time` | `drain TotalCurrent` | linear |
| `frequency` | `Frequency_GHz` or a detected frequency column | selected response | linear |

Do not label current as A/mm unless a device-width normalization factor is known and applied. Record every scale factor in the trace config.

### 3. Generate a starting configuration

Use `make-config` for common curves, then inspect the JSON before execution:

```powershell
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run-origin-bridge.ps1" make-config `
  --preset idvg `
  --input "path\to\n321_des.plt" "path\to\n404_des.plt" `
  --config "output\idvg.origin.json" `
  --dependent-project "D:\Sentaurus\my-device-project" `
  --project-name "idvg.opju" `
  --export "E:\Pictures\OriginPlot\my-device-project\idvg.png" "E:\Pictures\OriginPlot\my-device-project\idvg.svg"
```

For work with no dependent project, omit both `--dependent-project` and `--project`; the generated project target becomes `E:\Pictures\OriginPlot\Origin-Temp\<config-stem>.opju`.

For custom columns, use `--preset custom --x <column> --y <column>`. For an existing Origin graph template, add `--template <path-to-otp-or-otpu>`.

### Bundled single-Y and double-Y templates

Use the bundled publication templates when the user has not supplied a different Origin template. Both templates use Arial 30 pt bold text, 4-point axis and data lines, a borderless legend, balanced major-tick counts, `10^x` scientific notation, and a 600 dpi landscape page derived from the supplied RFSW reference style:

| Layout | Template asset | Use |
|---|---|---|
| Single Y | `assets/origin-single-y-arial30.otpu` | One shared Y axis for all traces |
| Double Y | `assets/origin-double-y-arial30.otpu` | Left and right Y axes with independent scales |

Select them through `make-config`; the bridge resolves the bundled asset automatically:

```powershell
# Single Y
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run-origin-bridge.ps1" make-config `
  --preset idvg --input "path\to\n321_des.plt" `
  --config "output\single-y.origin.json" `
  --figure-template single-y

# Double Y: the last trace is assigned to the right axis by default
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run-origin-bridge.ps1" make-config `
  --preset custom --input "path\to\n321_des.plt" "path\to\n321_des.plt" `
  --x "gate OuterVoltage" --y "drain TotalCurrent" `
  --right-y "SimStats Iterations" --right-y-title "Iterations" --right-y-scale linear `
  --config "output\double-y.origin.json" `
  --figure-template double-y --right-y-trace 2
```

For a double-Y graph, every trace must declare `axis` as `left` or `right`, and at least one trace must use each side. Use `--right-y-trace` with 1-based trace numbers to choose the right-axis traces. Use `--save-template <path.otpu>` when the finished styled graph should also be saved as a reusable Origin template.

Default to about seven major ticks on every visible axis so X, left Y, and right Y have comparable visual density. Respect an explicit axis `step`; use axis `major_ticks` to override the default count. Format log axes and automatically detected very small or large linear ranges with powers of ten, never `1E±x`. Keep ordinary linear axes in decimal notation. Read the RFSW-derived decisions in [references/config-and-presets.md](references/config-and-presets.md) before changing the bundled print style.

Read [references/config-and-presets.md](references/config-and-presets.md) before editing advanced transformations, axis limits, template settings, or multiple heterogeneous traces.

### 4. Dry-run and launch

Validate parsing, columns, transforms, log-axis positivity, paths, and overwrite policy without starting Origin:

```powershell
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run-origin-bridge.ps1" plot "output\idvg.origin.json" --dry-run
```

Only after the dry-run succeeds, create the Origin project and exports:

```powershell
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run-origin-bridge.ps1" plot "output\idvg.origin.json"
```

Use `--keep-open` only when the user wants interactive editing after automation. Otherwise save outputs and close the automation-owned Origin instance to avoid orphan processes.

### 5. Verify the deliverables

1. Confirm the `.opju` is inside the required `E:\Pictures\OriginPlot\<project-folder-name>` or `E:\Pictures\OriginPlot\Origin-Temp` directory and that it and every requested export exist and are non-empty.
2. Open at least one raster export with the local image viewer and inspect cropping, font size, axis labels, legend, curve separation, and log-scale behavior.
3. Confirm the plotted X/Y columns, signs, units, normalization factors, and input node/file provenance.
4. Keep an editable `.opju` as the primary artifact; treat exported images as derived deliverables.
5. Record output paths and key plotting choices in the project's `progress.md` or result report when such a file exists.

## Plotting standards

- Prefer an Origin template supplied by the user for exact journal styling.
- For raster output, default to at least 2400 px width; select dimensions consistent with at least 300 dpi at final print size.
- Prefer SVG, PDF, EPS, or EMF for vector delivery when the downstream workflow supports it.
- Use explicit axis titles and units. Use `|I_D|` only when the absolute-value transform is actually applied.
- Use colorblind-safe colors and do not encode critical distinctions by color alone when line style or symbols can help.
- For multi-sweep figures, keep trace order and legend order consistent with the physical sweep parameter.
- Avoid smoothing raw TCAD curves unless requested; if applied, retain raw data in the workbook and document the method.

## Troubleshooting

Read [references/origin-automation.md](references/origin-automation.md) when preflight fails, Origin cannot launch, a template fails, or an export is missing. Stop after two substantially identical automation failures; inspect the COM registration, interpreter/package pairing, and Origin UI state before retrying.
