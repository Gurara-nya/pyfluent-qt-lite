# `fluent_outputs` 目录说明

这个目录是 PyFluent 的仿真运行工作区。  
本次整理后，`fluent_outputs` 只保留这一个文档文件，其他内容全部清除。

## 目录定位

- 存放 Fluent 运行输入输出、日志、状态和后处理结果
- 作为“可重算”数据目录，默认不长期纳入代码仓库版本控制
- 仅用于工作流本地文件管理，不作为程序源码依赖

## 当前规则（统一执行）

- 保留：`fluent_outputs/README.md`
- 删除：`fluent_outputs` 下的所有其他文件与文件夹

## 常见文件类型（清理对象）

- Fluent 案例文件：`.cas`、`.cas.h5`
- 结果文件：`.dat`、`.dat.h5`
- 运行日志与状态：`.log`、`.out`、`.trn`、runner state/json
- 中间产物：`*.png`、`*.obj`、`*.csv`、`*.json`
- 运行临时目录：`workspace/`、`libudf/`、`_scratch/`、`runs/`

## 为什么可以删

- 这类文件体积大、变化快，且可通过脚本重跑或外部归档恢复
- 保持仓库轻量，便于后续代码维护与版本追踪
- 需要时再从外部归档恢复完整仿真记录

## 已执行动作

- `fluent_outputs` 内全部历史仿真目录与文件已清空，仅保留 `README.md`

