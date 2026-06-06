# fw1250_rerun_20260524

这是 `fw1250` 16 核同条件重算的运行日志目录。

- runner state：`fw1250_rerun1_state.json`
- Fluent 日志：`fw1250_rerun1_fluent.log`
- stdout/stderr：`fw1250_rerun1_stdout.log`、`fw1250_rerun1_stderr.log`

结果：Fluent 在 41-50 步附近断开，未生成 DAT。错误为 `StatusCode.UNAVAILABLE` / connection reset `10054`。该目录仅用于诊断与追溯。
