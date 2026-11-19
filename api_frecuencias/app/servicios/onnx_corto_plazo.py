"""El modelo de corto plazo en ONNX (spec v1.5 §9.1 «candidato tabular exportado a ONNX», §9.2 «ONNX Runtime»).

Cada artefacto es un LightGBM de Poisson: una suma de árboles de decisión sobre la matriz de variables de
variables_corto_plazo.py, cuya salida cruda (el logaritmo de la media) pasa por exp. La traducción a ONNX es directa y
no necesita otra librería que `onnx`:

- cada árbol se recorre desde la raíz y sus nodos quedan en un TreeEnsembleRegressor (dominio ai.onnx.ml, opset 3)
  con umbrales y hojas en doble precisión (los *_as_tensor), con la comparación de LightGBM (x <= umbral);
- un dato faltante (NaN) toma la rama que toma LightGBM: la de su `default_left` si el nodo aprendió faltantes
  (missing_type NaN) y, si no, la que tomaría el 0 (LightGBM lo trata como 0);
- un nodo Exp da la media de Poisson, la misma escala de booster.predict. La salida es float32 (la del operador en
  ai.onnx.ml 3), la misma precisión con que el experimento guardó sus predicciones.

Solo se usan divisiones numéricas (no hay variables categóricas en el corto plazo): si un árbol trae otra cosa, la
conversión falla en vez de dar otra predicción. scripts/exportar_onnx_corto_plazo.py exporta los 18 artefactos y
comprueba la paridad con LightGBM en las variables reales de la prueba reservada.
"""
from __future__ import annotations

import numpy as np

OPSET_ML = 3
OPSET = 17


def _recorrer(nodo: dict, arbol: int, acc: dict, contador: list) -> int:
    """Agrega el nodo (y sus hijos) a las listas del TreeEnsembleRegressor; devuelve su id dentro del árbol."""
    mio = contador[0]
    contador[0] += 1
    if "leaf_value" in nodo:
        acc["nodes_treeids"].append(arbol)
        acc["nodes_nodeids"].append(mio)
        acc["nodes_featureids"].append(0)
        acc["nodes_modes"].append("LEAF")
        acc["nodes_values"].append(0.0)
        acc["nodes_truenodeids"].append(0)
        acc["nodes_falsenodeids"].append(0)
        acc["nodes_missing"].append(0)
        acc["target_treeids"].append(arbol)
        acc["target_nodeids"].append(mio)
        acc["target_ids"].append(0)
        acc["target_weights"].append(float(nodo["leaf_value"]))
        return mio
    if nodo.get("decision_type") != "<=" or nodo.get("missing_type") == "Zero":
        raise ValueError(f"división no numérica en el árbol {arbol}: {nodo.get('decision_type')}")
    pos = len(acc["nodes_nodeids"])
    for k, v in (("nodes_treeids", arbol), ("nodes_nodeids", mio), ("nodes_featureids", int(nodo["split_feature"])),
                 ("nodes_modes", "BRANCH_LEQ"), ("nodes_values", float(nodo["threshold"])), ("nodes_truenodeids", 0),
                 ("nodes_falsenodeids", 0), ("nodes_missing", 0)):
        acc[k].append(v)
    izquierdo = _recorrer(nodo["left_child"], arbol, acc, contador)
    derecho = _recorrer(nodo["right_child"], arbol, acc, contador)
    acc["nodes_truenodeids"][pos], acc["nodes_falsenodeids"][pos] = izquierdo, derecho
    if nodo.get("missing_type") == "NaN":
        acc["nodes_missing"][pos] = int(bool(nodo.get("default_left")))
    else:                                         # sin faltantes aprendidos: LightGBM trata el NaN como 0
        acc["nodes_missing"][pos] = int(0.0 <= float(nodo["threshold"]))
    return mio


def _tensor(nombre: str, valores):
    from onnx import numpy_helper

    return numpy_helper.from_array(np.asarray(valores, dtype=np.float64), nombre)


def convertir(booster, nombre: str = "corto_plazo"):
    """El booster de LightGBM (objetivo poisson) como un modelo ONNX: entrada X (double, [N, F]), salida Y (float32,
    [N, 1])."""
    from onnx import TensorProto, helper

    d = booster.dump_model()
    objetivo = str(d.get("objective", "")).split()[0]
    if objetivo != "poisson":
        raise ValueError(f"objetivo {objetivo!r}: la conversión es para LightGBM de Poisson")
    nf = int(d["max_feature_idx"]) + 1
    acc = {k: [] for k in ("nodes_treeids", "nodes_nodeids", "nodes_featureids", "nodes_modes", "nodes_values",
                           "nodes_truenodeids", "nodes_falsenodeids", "nodes_missing", "target_treeids",
                           "target_nodeids", "target_ids", "target_weights")}
    for t in d["tree_info"]:
        _recorrer(t["tree_structure"], int(t["tree_index"]), acc, [0])
    arbol = helper.make_node(
        "TreeEnsembleRegressor", ["X"], ["log_media"], domain="ai.onnx.ml", n_targets=1, aggregate_function="SUM",
        post_transform="NONE", nodes_treeids=acc["nodes_treeids"], nodes_nodeids=acc["nodes_nodeids"],
        nodes_featureids=acc["nodes_featureids"], nodes_modes=acc["nodes_modes"],
        nodes_values_as_tensor=_tensor("nodes_values", acc["nodes_values"]),
        nodes_truenodeids=acc["nodes_truenodeids"], nodes_falsenodeids=acc["nodes_falsenodeids"],
        nodes_missing_value_tracks_true=acc["nodes_missing"], target_treeids=acc["target_treeids"],
        target_nodeids=acc["target_nodeids"], target_ids=acc["target_ids"],
        target_weights_as_tensor=_tensor("target_weights", acc["target_weights"]),
        base_values_as_tensor=_tensor("base_values", [0.0]))
    media = helper.make_node("Exp", ["log_media"], ["Y"])
    grafo = helper.make_graph([arbol, media], nombre,
                              [helper.make_tensor_value_info("X", TensorProto.DOUBLE, [None, nf])],
                              [helper.make_tensor_value_info("Y", TensorProto.FLOAT, [None, 1])])
    modelo = helper.make_model(grafo, opset_imports=[helper.make_opsetid("", OPSET),
                                                     helper.make_opsetid("ai.onnx.ml", OPSET_ML)],
                               producer_name="api_frecuencias.onnx_corto_plazo")
    modelo.ir_version = 9
    return modelo


def sesion(modelo_bytes: bytes):
    import onnxruntime as ort

    opciones = ort.SessionOptions()
    opciones.intra_op_num_threads = 1
    return ort.InferenceSession(modelo_bytes, sess_options=opciones, providers=["CPUExecutionProvider"])


def predecir(sesion_onnx, x: np.ndarray) -> np.ndarray:
    return sesion_onnx.run(["Y"], {"X": np.asarray(x, dtype=np.float64)})[0][:, 0]
