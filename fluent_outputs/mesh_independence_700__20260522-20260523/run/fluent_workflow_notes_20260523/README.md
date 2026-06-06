# Fluent 计算流程整理草案

本文件夹整理本轮 D40 fuel-wall 网格无关性验证中实际用到的 Fluent 批量计算、DAT 验收、结果解析和报告输出流程。它先作为项目内流程记录使用，等我们确认哪些参数应该固定、哪些参数应该开放后，再抽成更泛化的 Codex skill。

## 文件

- [01_fluent_batch_calculation.md](01_fluent_batch_calculation.md)
  记录 mesh 扫描、单个 Fluent job、重试、保存 cas/dat 的计算流程。
- [02_dat_acceptance_and_analysis.md](02_dat_acceptance_and_analysis.md)
  记录 DAT HDF5 文件验收、fuel-wall 指标解析、异常点剔除和绘图口径。
- [03_command_templates.md](03_command_templates.md)
  保存本轮可复用的 dry-run、批量运行、单点 rerun、后处理命令模板。
- [04_generalization_questions.md](04_generalization_questions.md)
  列出转成泛化 skill 前建议确认的问题。
- [source_index.md](source_index.md)
  汇总本流程依赖的脚本、运行记录、报告和原始数据位置。

## 本轮流程一句话

批量脚本在 mesh 根目录下发现所有 `*-fluent.msh`，每个 mesh 用同一 base case 读入并保留 case 设置，加载同一 UDF，执行固定初始化工作流和 `combo-256` 参数，计算 700 步，保存新的 prepared cas 和 dat；随后用 HDF5 结构和 residual iteration 数做 dat 文件级验收，再用 fuel-wall UDM、face zone 和 residual final 做物理验收、绘图和报告。

## 关键项目参数

| 参数 | 本轮取值 |
|---|---|
| mesh 根目录 | `D:\Workshop\Mesh\d-40\codex-mesh-package\04-fuelend040-060-revisit\fuelend040-060-revisit` |
| work/output 目录 | `F:\pyfluent_qt_lit\fluent_outputs\mesh_independence_700__20260522-20260523\cas_dat` |
| base case | `F:\pyfluent_qt_lit\fluent_outputs\mesh_independence_700__20260522-20260523\cas_dat\standard-bl12um-h290um.cas.h5` |
| UDF 目录 | `D:\Workshop\UDF\dpm-cal-udf` |
| combo | `combo-256` |
| 计算步数 | `700` |
| Fluent cores | `16` |
| 自动重试 | `CODEX_BATCH_MAX_ATTEMPTS=0` 表示不限次数，直到文件级验收通过或人工停止 |

## 需要特别记住

本轮“计算完成”分两层：

1. 文件级完成：runner 返回成功，DAT 存在、非空、能用 HDF5 打开，并且 continuity residual iteration 数达到 700。这一层由批量脚本自动判断并决定是否重试。
2. 物理验收完成：DAT 中 residual final、燃速、fuelwall 壁温达到合理阈值。这一层在后处理脚本中判断；异常点后续可按分析策略排除，而不一定触发自动重算。

讨论后的推荐策略：

- Fluent 崩溃、runner 返回失败、DAT 不完整、DAT 不可读、迭代数不足：可以持续重试，因为 Fluent 本身存在偶发崩溃概率。
- 物理异常：可以有限重试 1-2 次；如果仍然异常，应标记为有问题，通常说明工况、UDF 或设置存在问题，不再无限消耗计算时间。
- 验收阈值、关注指标和图表口径不写死为通用规则。每次任务都由用户配置，因为不同轮次关注的 fuel-wall 指标、局部区域和异常判据可能不同。
