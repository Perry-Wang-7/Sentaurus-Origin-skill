<div align="center">

# Sentaurus-Origin Skill

**让 Codex 将 Sentaurus TCAD 曲线数据自动转换为可编辑的 Origin 工程和投稿级图片。**

![Codex Skill](https://img.shields.io/badge/Codex-Skill-4B32C3)
![Platform](https://img.shields.io/badge/platform-Windows-0078D4)
![Origin](https://img.shields.io/badge/Origin-2021%2B-F28C28)

</div>

`sentaurus-origin-skill` 连接 Codex、Sentaurus 和 Origin/OriginPro。它能检查 DF-ISE 文本 `.plt`、CSV、TSV 或 XLSX 数据，生成可编辑的 `.opju` 工程，并导出 PNG、TIFF、SVG、PDF、EPS 或 EMF 图片。

## 功能

- 解析 Sentaurus DF-ISE 文本 `.plt`，并检查字段和曲线数据。
- 支持 Id-Vg、Id-Vd、击穿、瞬态、频率及自定义 XY 曲线。
- 创建新的 Origin 自动化实例，不修改用户已经打开的工程。
- 内置单 Y 轴和双 Y 轴 Origin 模板。
- 统一使用 Arial 30 pt 加粗字体、4 pt 坐标轴和数据线、无边框图例。
- 将科学计数法显示为 `10^x`，并平衡各坐标轴的主刻度密度。
- 生成适合打印的 600 dpi 横向页面，同时保留可编辑 `.opju`。
- 自动把工程保存到 `E:\Pictures\OriginPlot\<项目文件夹名>`；没有依赖项目时使用 `Origin-Temp`。

## 安装

### npx skills

查看仓库中的可安装技能：

```powershell
npx skills add Perry-Wang-7/Sentaurus-Origin-skill --list
```

全局安装到 Codex：

```powershell
npx skills add Perry-Wang-7/Sentaurus-Origin-skill --global --agent codex --skill sentaurus-origin-skill --yes --copy
```

### 手动安装

```powershell
git clone https://github.com/Perry-Wang-7/Sentaurus-Origin-skill.git
New-Item -ItemType Directory -Path "$env:USERPROFILE\.codex\skills" -Force
Copy-Item -Recurse ".\Sentaurus-Origin-skill\skills\sentaurus-origin-skill" "$env:USERPROFILE\.codex\skills\"
```

安装或更新后，请开启新的 Codex 任务，使技能被完整发现。

## 运行依赖

- Windows。
- 已安装并授权的 Origin/OriginPro 2021 或更高版本。
- Python 3。
- 实际控制 Origin 和生成 `.opju` 时需要 OriginLab 的 `originpro` 包。
- 读取 XLSX 时额外需要 `pandas` 和 `openpyxl`；读取 DF-ISE `.plt`、CSV 和 TSV 不需要这两个包。

按需安装 Python 包：

```powershell
python -m pip install originpro
python -m pip install pandas openpyxl  # 仅 XLSX 输入需要
```

## 快速开始

技能安装后，可以直接对 Codex 说：

```text
使用 sentaurus-origin-skill，把这些 Sentaurus Id-Vg 结果画成 Origin 单 Y 轴图，
保存可编辑 opju，同时导出 PNG 和 SVG。
```

也可以直接运行桥接脚本。先检查环境：

```powershell
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run-origin-bridge.ps1" preflight
```

检查数据字段：

```powershell
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run-origin-bridge.ps1" inspect "path\to\n123_des.plt"
```

生成配置后先进行不启动 Origin 的验证，再正式绘图：

```powershell
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run-origin-bridge.ps1" plot "output\idvg.origin.json" --dry-run
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run-origin-bridge.ps1" plot "output\idvg.origin.json"
```

完整工作流、预设和参数说明见 [`SKILL.md`](skills/sentaurus-origin-skill/SKILL.md)。

## 仓库结构

```text
skills/
└── sentaurus-origin-skill/
    ├── SKILL.md
    ├── agents/
    │   └── openai.yaml
    ├── assets/
    │   ├── origin-single-y-arial30.otpu
    │   └── origin-double-y-arial30.otpu
    ├── references/
    │   ├── config-and-presets.md
    │   └── origin-automation.md
    └── scripts/
        ├── origin_bridge.py
        └── run-origin-bridge.ps1
```

技能必须以完整目录安装。不要只复制 `SKILL.md`，否则 Origin 模板、桥接脚本和参考配置将不可用。

## 安全原则

- 在把曲线作为科学证据前，先确认 Sentaurus 仿真正常完成。
- `.tdr` 空间分布继续使用 Sentaurus Visual 检查；Origin 主要用于 XY 曲线和最终排版。
- 默认不覆盖已有 `.opju`，并避免附加到用户正在编辑的 Origin 会话。
- 正式启动 Origin 前先执行 dry-run，确认列名、单位、变换和输出路径。
