"""
sweep_config.py
---------------
参数扫描配置: 定义要扫描的 Fluent rpvar 及其取值列表。

本文件可由 PyFluent Lite 的“参数扫描”页写回。
"""

PARAM_GRID: dict[str, list[float]] = {
    'udf/a-ent'     : [5e-12, 1e-11, 2e-11],
    'udf/evap-a'    : [100, 1000, 2000],
    'udf/evap-ea'   : [50000, 80000, 110000],
    'udf/lambda-ent': [1.2, 1.5, 1.8],
    'udf/theta-ent' : [1.2, 1.5, 1.8],
}
