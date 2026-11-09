"""Optimizador D5 (MILP de salidas por hora) copiado del proyecto para la API de frecuencias.

Nota de origen (cadena de copias, sin cambios de lógica):
- milp.py: copia exacta (mismo SHA-256) de EntregaFinal/dash_app/motor/milp.py, que a su vez es copia exacta de
  experimentos/D5_optimizacion_milp/milp.py.
- plan_base.py: copia exacta de EntregaFinal/dash_app/motor/plan_base.py (versión reducida de
  sistema_tiempo_real/plan_base.py): insumos, entradas del MILP, oráculo, horario y plan_ruta().
- comun.py: copia de EntregaFinal/dash_app/motor/comun.py; solo cambia la carpeta de datos (variable DATA_DIR, por
  defecto api_frecuencias/datos/) y se quitan las funciones de formato del tablero.
Datos que lee (copiados de EntregaFinal/dash_app/datos/): insumos_d5_2025.parquet, pronosticos_2025.parquet y
costos_fuente.json.
"""
