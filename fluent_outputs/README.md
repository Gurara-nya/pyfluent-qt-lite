# Fluent 输出文件管理索引

本文档用于快速查看 `fluent_outputs/` 下每个项目文件夹的用途、日期、背景、结果和关键文件。当前采用“按项目管理”的方式：每个项目目录内部再放 `cas_dat/`、`run/`、`workspace/`、`post/` 等子目录。

## 目录规则

推荐新项目使用以下结构：

```text
fluent_outputs/
  <项目名_日期>/
    README.md
    cas_dat/
    run/
    post/
    workspace/
```

- `cas_dat/`：Fluent 生成或使用的 `.cas`、`.cas.h5`、`.dat`、`.dat.h5` 等大文件；如果是同一项目的补算或重算，按 tag 新建子目录。
- `run/`：批处理日志、runner state、manifest、分析表、图、报告和状态说明。
- `post/`：后处理图件、CSV/JSON 结果、网格无关性验证报告。
- `workspace/`：该项目专用的 Fluent 临时工作目录。

命名建议：

- 项目目录使用“内容/标签 + 日期”，例如 `nofuel_standard_v2_700__20260524`。
- 属于同一研究问题的补算、重算、诊断、probe，优先并入该项目目录下的 tag 子目录。
- 顶层不再放 `cas_dat/`、`runs/`、`workspace/` 这类跨项目目录。

## 当前项目台账

| 项目文件夹 | 日期 | 背景/目的 | 当前结果 | 关键文件 |
|---|---|---|---|---|
| `nofuel_standard_v2_700__20260524` | 2026-05-24 | 对 `D:\Workshop\Mesh\d-40\codex-mesh-package\06-nofuel-standard-v2` 中 6 个 nofuel standard-v2 Fluent 网格做 700 步计算。 | 当前选用的 6 个 DAT 均已通过文件级和物理校验：`fw750`、`fw1000`、`fw1750`、`fw2000` 来自 16 核主批处理；`fw1250` 来自 8 核标准 case 重算；`fw1500` 来自 8 核 `flowsoft-lr` 补算。原始 `fw1250` 物理异常，已被重算结果替代；`fw1250` 16 核同条件重算在 41-50 步断开，保留为诊断记录。当前不同 msh 后处理已完成并放入 `post/`。严格同条件网格无关性仍不建议直接判定通过，因为 `fw1250` 和 `fw1500` 使用 8 核补算路径，且主批处理 `fw1750 -> fw2000` 的燃速/Gf 差异约 `1.81%`。 | `README.md`、`run/STATUS.md`、`post/README.md`、`post/figures/`、`post/dat_plots/`、`cas_dat/fw1250_rerun_8core_20260524/`、`cas_dat/fw1500_flowsoftlr_8core_recovery/` |
| `mesh_independence_700__20260522-20260523` | 2026-05-22 至 2026-05-23 | 之前一轮 700 步网格无关性计算和交付归档，包含批处理结果、物理异常重试、分析输出和最终 deliverable。 | 已形成分析结果和交付包；作为历史基线，用于复查上一轮 mesh-independence 工作流程和结果。 | `run/manifest.csv`、`run/batch_state.json`、`run/analysis/`、`run/mesh_independence_deliverable_20260523/` |
| `manual_sessions__default` | 持续使用 | PyFluent Lite 手动会话的默认工作目录。没有明确项目目录时，桌面 app 默认把手动 Fluent 工作文件放在这里。 | 作为默认 workspace 保留；正式 campaign 建议新建独立项目目录。 | `workspace/` |
| `_scratch` | 2026-05-17 起 | 临时 smoke test、菜单探针、路径测试和短期实验归档，不属于正式 campaign。 | 只作临时资料保留；如果某个 scratch 结果变成正式依据，应迁移到独立项目目录。 | `_scratch/README.md`、`_scratch/20260517_smoke-and-probes/` |

## nofuel standard-v2 当前结论

当前 nofuel standard-v2 六个网格均已有当前选用的 700 步有效 DAT 覆盖：

- `fw750`、`fw1000`、`fw1750`、`fw2000` 来自主项目的 16 核主批处理。
- `fw1250` 来自 `fw1250_rerun_8core_20260524`，用于替代原始物理异常 DAT。
- `fw1500` 来自 `fw1500_flowsoftlr_8core_recovery`。

注意：如果后续需要严格比较“同一基准 case、同一核数”的结果，建议将 6 个网格统一用同一个基准 case 和同一核数重跑一轮。如果目标是先补齐每个网格的 700 步有效结果，当前目录已经覆盖完整。

## 维护记录

- 2026-05-24：将 `fw1500` 的 8 核 `flowsoft-lr` 成功补算合并到 `nofuel_standard_v2_700__20260524` 主项目内；移除失败的 16 核 probe 独立目录，避免后期误认为它是有效项目。
- 2026-05-24：发现原始 `fw1250` DAT 物理异常；16 核同条件重算在 41-50 步断开；8 核标准 case 重算成功并替代原始 `fw1250` 进入当前 `post/` 分析。

## 维护规则

- 新 campaign 或独立研究问题建立独立项目目录。
- 同一项目内的补算、probe、重跑结果放在项目内部按 tag 命名的子目录。
- 每个项目目录都应有中文 `README.md`，说明背景、输入、日期、结果和关键文件。
- 阶段性计算状态写入项目的 `run/STATUS.md`。
- 后处理结论写入项目的 `post/README.md`。
- 大体量 `.cas/.dat/.h5/log` 保持被 git 忽略；项目级 `README.md`、`run/STATUS.md` 和 `post/README.md` 作为管理文档保留。
- 不要再恢复顶层 `cas_dat/`、`runs/`、`workspace/` 旧布局。
