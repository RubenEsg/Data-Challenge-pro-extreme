"""Motor del laboratorio: copias del optimizador del proyecto que leen de dash_app/datos/.

- milp.py: copia exacta de experimentos/D5_optimizacion_milp/milp.py (núcleo del MILP de D5, sin cambios).
- comun.py: versión reducida de sistema_tiempo_real/comun.py (constantes, formato de números y param_d5()).
- plan_base.py: versión reducida de sistema_tiempo_real/plan_base.py (insumos, entradas del MILP, oráculo y horario), con
  el pronóstico del modelo elegido como en sistema_tiempo_real/motor.py (mu + log(c)).
- evaluacion.py: evaluar() de experimentos/D5_optimizacion_milp/run.py para un día (contabilidad con la demanda real).
"""
