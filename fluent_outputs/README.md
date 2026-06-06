# Fluent 输出目录说明

本目录用于集中管理 `pyfluent_qt_lite` 的 Fluent 计算产物和手工会话文件。  
这里主要放的是运行时数据，不是程序源码；默认可清理、可归档，不影响应用本身。

## 一、这个文件夹的角色

- `fluent_outputs` 是项目级运行区，所有实际算例相关文件都放在这里，便于按任务独立管理。
- 下层每个项目目录用于一次完整工作单元：输入网格/基准 case、批处理运行、后处理结果、临时工作文件都各自归属。
- 仓库里 `.gitignore` 已经默认忽略了大部分运行产物（`*.cas`、`*.dat`、`*.h5`、`*.log` 等），只保留必要文档文件便于追溯。

## 二、推荐目录结构（长期规范）

```text
fluent_outputs/
  manual_sessions__default/
    workspace/
    README.md
  _scratch/
    <tag>/           # 临时实验目录
    README.md
  <campaign-name>__<date-tag>/
    cas_dat/          # 计算输入/输出：case、dat 等（可清理）
    run/              # 运行状态：manifest、batch state、日志、状态说明
    post/             # 后处理：图、汇总 csv/json、统计说明
    workspace/        # 项目级工作区（可保留，不含长期依赖数据时可清）
    README.md
    run/STATUS.md     # 可选，记录跑步状态
    post/README.md    # 可选，记录后处理口径与结论
```

## 三、目录命名规范

### 1）项目目录
- 形如 `<campaign-name>__<date-tag>`，例如：
  - `nofuel_standard_v2_700__20260524`
  - `mesh_independence_700__20260522-20260523`
- `campaign-name` 说明任务含义；`date-tag` 建议：
  - 单日任务：`YYYYMMDD`
  - 跨日任务：`YYYYMMDD-YYYYMMDD`

### 2）子目录命名
- `cas_dat`：case/dat 相关文件、重算片段、UDF 工作副本。
- `run`：执行态文件（manifest、日志、runner state、重跑说明）。
- `post`：后处理输出（图、表、报告、可复现实验说明）。
- `workspace`：局部工作目录；若仅用于短时调试可在清理时保留空目录结构。

### 3）运行分支目录（可选）
- 在 `run` 下允许出现按任务标识的子目录：  
  `fw1500_probe_8core_20260524`、`fw1250_rerun_8core_20260524` 等。
- 这些子目录也按同样原则保留说明文件，清理时以时间优先级或是否归档为准。

## 四、`fluent_outputs` 中现在有什么（可清理范围）

默认可清理的为“运行数据和结果”：
- Fluent 运行文件：`*.cas`、`*.cas.h5`、`*.dat`、`*.dat.h5`、`*.trn` 等
- 执行日志与状态：`*.log`、runner state/json、stdout/stderr
- 可视化和导出结果：`*.png`、`*.jpg`、`*.obj`、`*.stl`、`*.csv`、`*.json`（若不作长期归档）
- 运行临时目录下的中间脚本、缓存与中间产物

不建议清理（建议长期保留）：
- 各层 `README.md`
- 项目关键记录文件如 `run/STATUS.md`、`post/README.md`（可选）
- `fluent_outputs` 的目录结构本身（用于下一轮继续运行）

## 五、清理策略（建议）

1. 每次任务结束后，先确认是否需要归档（例如导出到外部仓库/网盘）。
2. 归档后可按以下策略清理：
   - 保留：`README.md`、`STATUS.md`（如存在）、空目录。
   - 删除：除以上以外的所有文件。
3. 若要保留可追溯性，`run` 可保留 `manifest` 与 `status`，将大体积结果文件（`dat/cas/h5`）移入归档。

## 六、目录内现有内容示例（基线目录）

- `manual_sessions__default`：手动会话默认工作目录占位（建议只保留说明文件和空 `workspace/` 骨架）。
- `_scratch`：临时验证目录，实验类任务结束后可直接清空。
- 其余 `nofuel_standard_v2...`、`mesh_independence_700...`：均为历史 campaign，完成后可按上述策略清理重算产物。

## 七、常见问题

- **这个目录可以删吗？** 可以。该目录是计算产物区，清理后不会影响源码；脚本若再次运行，会在路径下重新创建需要的目录与输出。
- **是否必须删完？** 不必一次性全删。建议保留说明文档和目录结构，删除重型二进制和结果文件即可。

## 八、变更记录

- 2026-06-06：完成 `fluent_outputs` 使用说明梳理，明确项目结构、命名规范与清理规则，准备统一清理历史运行数据。
