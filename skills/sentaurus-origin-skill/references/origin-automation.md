# Origin automation setup and troubleshooting

## Contents

- Supported architecture
- Dependency setup
- COM registration
- Templates and exports
- Session safety
- Failure triage
- Primary documentation

## Supported architecture

Use external Python with OriginLab's `originpro` package. The package controls Origin through its Windows Automation Server/COM interface and can create worksheets, graphs, exports, and project files. It requires Windows and a locally installed, licensed Origin 2021 or later.

The bridge does not use image recognition or mouse automation. It communicates through documented Origin objects and keeps the editable `.opju` as the primary output.

## Dependency setup

Run `preflight` with the same interpreter that will execute `plot`. If `originpro_version` is null, install into that interpreter only after obtaining permission:

```powershell
& "<python.exe>" -m pip install originpro
```

XLSX input additionally requires `pandas` and `openpyxl`. DF-ISE `.plt`, CSV, and TSV parsing use the Python standard library.

Avoid mixing a working `originpro` installation from one Python with another interpreter. Confirm the interpreter path reported by preflight.

## COM registration

Preflight checks `Origin.ApplicationSI` and `Origin.Application`. If Origin is installed but neither ProgID is registered:

1. Locate the real `Origin64.exe` rather than an empty or stale installation directory.
2. Start the intended Origin version once and close it normally.
3. If registration is still missing, follow the OriginLab installation/Automation Server repair instructions. Do not edit CLSID registry keys manually.
4. Re-run preflight and confirm the registered executable exists.

## Templates and exports

- The skill bundles `origin-single-y-arial30.otpu` and `origin-double-y-arial30.otpu` under `assets`; select them with `--figure-template single-y` or `--figure-template double-y`.
- Both bundled templates use Arial 30 pt bold text, 4-point axis and data lines, a borderless legend, balanced major-tick counts, `10^x` scientific notation, and a 600 dpi landscape print page.
- Use a full path for custom `.otp` or `.otpu` templates.
- Test templates with one trace before a batch plot.
- A template can control page size, fonts, line widths, symbols, layers, and export behavior more reliably than ad hoc LabTalk styling.
- `--save-template <path.otpu>` saves the finished graph as another reusable Origin graph template.
- `save_fig` uses the export extension to select PNG, TIFF, SVG, PDF, EPS, EMF, or another supported Origin format.
- Verify the actual output file because format support and template/export settings can vary by Origin version.

## Session safety

- The bridge creates a blank project in an automation-owned Origin instance.
- It does not call `attach()` and does not modify a user's existing interactive project.
- With `keep_open` false, it saves outputs and calls `op.exit()` for the automation instance.
- If Origin 2025b leaves that automation-owned PID idle after COM exit, the bridge terminates only the PID created during the current run. Origin processes present before the run are excluded.
- With `--keep-open`, it leaves the instance visible for manual editing. The user becomes responsible for saving and closing it.
- During debugging keep Origin visible; hidden instances make errors and orphaned processes harder to diagnose.

## Failure triage

### Import succeeds but Origin does not launch

Check COM registration, Origin licensing, and whether a modal Origin dialog is waiting behind another window. Confirm that the Python and Origin architectures are compatible.

### Template creation fails

Remove the template path and test the default graph. Then verify the template opens in the same Origin version and is a graph template rather than a workbook or project template.

### Log plot loses points

Read the dry-run `dropped` count. Log axes require positive values. Confirm whether absolute current is scientifically appropriate; do not silently add an arbitrary floor.

### Export is absent or clipped

Open the graph in Origin, verify page and layer dimensions, then test a PNG export before vector/raster batch export. Use a verified template for journal-specific page size and font rules.

### Repeated failure

After two substantially identical failures, stop retrying. Capture the exact exception, preflight JSON, config, Origin version, and whether a modal UI dialog is present.

## Primary documentation

- External Python overview: https://docs.originlab.com/externalpython/
- External Python samples: https://docs.originlab.com/externalpython/external-python-code-samples/
- OriginLab Python examples: https://github.com/originlab/Python-Samples
- `new_graph`, `new_sheet`, `save`: https://docs.originlab.com/originpro/namespaceoriginpro_1_1project.html
- Graph export: https://docs.originlab.com/originpro/classoriginpro_1_1graph_1_1GPage.html
- Graph layer and plots: https://docs.originlab.com/originpro/classoriginpro_1_1graph_1_1GLayer.html
- Axis properties: https://docs.originlab.com/originpro/classoriginpro_1_1graph_1_1Axis.html
- Worksheet import: https://docs.originlab.com/originpro/classoriginpro_1_1worksheet_1_1WSheet.html
