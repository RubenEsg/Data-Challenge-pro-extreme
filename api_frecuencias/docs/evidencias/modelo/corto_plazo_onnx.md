# Modelo de corto plazo en ONNX: exportación y paridad

Generado por `scripts/exportar_onnx_corto_plazo.py` el 2026-11-19 para `cp_lgbm_20250630_s42` (spec v1.5 §9.1 «candidato tabular exportado a ONNX», §9.2).

Cada uno de los 18 artefactos de LightGBM (nivel ruta y segmento, horizontes de 30, 60 y 120 minutos, tres rutas) se tradujo a un modelo ONNX: un `TreeEnsembleRegressor` (ai.onnx.ml 3) con los mismos umbrales y hojas en doble precisión, la misma regla para los faltantes y un `Exp` (el objetivo es Poisson). Los archivos quedan comprimidos en `datos/modelos/corto_plazo/<model_id>/onnx/`, con su SHA-256 en `manifest_onnx.json`; con `MOTOR_INFERENCIA=onnx` la API pronostica con ONNX Runtime y verifica cada hash al cargar.

Paridad con LightGBM: 490.140 filas reales de seis días de la prueba reservada (uno por mes. todas las medias horas de 04:00 a 21:00) más las mismas filas con un 10 % de valores faltantes. Diferencia relativa máxima: **4.9e-07** (tolerancia 1e-05. la precisión de float32). Paridad: **sí**.

| Artefacto | Árboles | Filas | Diferencia relativa máxima | ONNX (MB, comprimido) | SHA-256 |
|---|---:|---:|---:|---:|---|
| `ruta_h120_r16` | 400 | 420 | 4.9e-07 | 0.38 | `59e26d024542bae5…` |
| `ruta_h120_r2` | 400 | 420 | 2.7e-07 | 0.38 | `d519bbd676864aac…` |
| `ruta_h120_r21` | 400 | 420 | 2.8e-07 | 0.38 | `4063ba1903026695…` |
| `ruta_h30_r16` | 400 | 420 | 3.0e-07 | 0.38 | `3116845a0581c805…` |
| `ruta_h30_r2` | 400 | 420 | 2.8e-07 | 0.38 | `6e92d22b203aaf2e…` |
| `ruta_h30_r21` | 400 | 420 | 2.7e-07 | 0.38 | `4fb1a7c701e67aa0…` |
| `ruta_h60_r16` | 400 | 420 | 2.8e-07 | 0.38 | `c4887d5a01a052d9…` |
| `ruta_h60_r2` | 400 | 420 | 2.9e-07 | 0.38 | `c93630a1bc5a5f07…` |
| `ruta_h60_r21` | 400 | 420 | 2.7e-07 | 0.38 | `825f4d95b1e068dd…` |
| `segmento_h120_r16` | 300 | 51.660 | 2.9e-07 | 0.57 | `90d16e4ab445d83b…` |
| `segmento_h120_r2` | 300 | 56.700 | 2.9e-07 | 0.57 | `0e2f08ea69b1e1ad…` |
| `segmento_h120_r21` | 300 | 53.760 | 2.7e-07 | 0.57 | `457674c6f3c1ac5b…` |
| `segmento_h30_r16` | 300 | 51.660 | 3.4e-07 | 0.57 | `b04df31ac3b722ea…` |
| `segmento_h30_r2` | 300 | 56.700 | 2.9e-07 | 0.57 | `a7804b842c066448…` |
| `segmento_h30_r21` | 300 | 53.760 | 2.8e-07 | 0.57 | `4549788bceaac0b6…` |
| `segmento_h60_r16` | 300 | 51.660 | 2.9e-07 | 0.57 | `c6642993e4856cf1…` |
| `segmento_h60_r2` | 300 | 56.700 | 2.9e-07 | 0.57 | `c76a8fc05409f888…` |
| `segmento_h60_r21` | 300 | 53.760 | 2.9e-07 | 0.57 | `9316adfeb52f2001…` |

La explicación local (TreeSHAP) sigue saliendo de LightGBM (`pred_contrib`): ONNX solo da la predicción.
