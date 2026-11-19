"""La lectura del corto plazo en modo integrado (RF-005, RF-013, §11.2) contra la réplica, en solo lectura (lector_ia):
fuentes.leer_panel_15min re-agrega un día de timbradas_segmentos (lo que escriben los scripts de Extreme) y de
progvehiculos por segmento oficial y bloque de 15 minutos, y se compara con el panel empaquetado del experimento E14
(que asignó cada evento de conteo al segmento más cercano con la misma regla) en un día histórico de la réplica.

Lo que se puede exigir en un día histórico, por los hallazgos de docs/hallazgos_extreme.md:
- el SEGMENTO y las SALIDAS coinciden (correlación de las subidas por segmento ≥ 0,998; las mismas salidas por bloque);
- el total es algo menor (H6: el cargue inicial descarta los viajes sin fecha de fin, entre el 1 % y el 11 % de las
  subidas del día);
- el BLOQUE no: el cargue inicial (script 5) pone todos los segmentos de un viaje en el bloque del fin del viaje
  (H10). Lo que llega en vivo lo escribe el trigger de conteo, con el bloque de cada subida, que es lo que necesita
  el pronóstico de corto plazo.

Con GENERAR_EVIDENCIAS=1 la comparación queda en docs/evidencias/replica/panel_corto_plazo_replica_<idruta>.json.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from scripts import replica_comun as rc
from tests.evidencia import guardar_evidencia

psycopg = pytest.importorskip("psycopg")
DIA = date(2023, 2, 14)          # martes con datos de las tres rutas en la carga


@pytest.fixture(scope="module")
def fuente(cargada):
    from app.servicios.fuentes import FuentePostgresSoloLectura

    url = rc.url_rol("lector_ia")
    if not url:
        pytest.skip("falta LECTOR_IA_PASSWORD")
    f = FuentePostgresSoloLectura(url=url.replace("postgresql://", "postgresql+psycopg://"))
    yield f
    f._engine().dispose()


@pytest.mark.parametrize("idruta", [2, 16, 21])
def test_la_lectura_de_15_minutos_de_la_replica_da_el_segmento_y_las_salidas_del_panel(fuente, idruta):
    from app.servicios import panel_corto_plazo as P

    hasta = datetime(2030, 1, 1, tzinfo=ZoneInfo("America/Bogota"))
    sub, sal = P.de_la_fuente(fuente, idruta, [DIA], hasta)
    ref_sub, ref_sal = P.del_panel(idruta, [DIA])
    assert len(sub) and len(sal) and fuente.resumen_panel["truncada"] is False
    por_seg = sub.groupby("nro_segmento")["subidas"].sum()
    ref_seg = ref_sub.groupby("nro_segmento")["subidas"].sum()
    comunes = por_seg.index.union(ref_seg.index)
    a, b = por_seg.reindex(comunes, fill_value=0), ref_seg.reindex(comunes, fill_value=0)
    corr_seg = float(np.corrcoef(a, b)[0, 1])
    total, ref_total = float(a.sum()), float(b.sum())
    salidas = sal.groupby("bloque")["salidas"].sum().to_dict()
    ref_salidas = ref_sal.groupby("bloque")["salidas"].sum().to_dict()
    guardar_evidencia(f"replica/panel_corto_plazo_replica_{idruta}.json", {
        "idruta": idruta, "dia": DIA, "subidas_replica": total, "subidas_panel": ref_total,
        "proporcion": round(total / ref_total, 4), "correlacion_por_segmento": round(corr_seg, 5),
        "salidas_replica": float(sal["salidas"].sum()), "salidas_panel": float(ref_sal["salidas"].sum()),
        "nota": "por bloque no se compara: el cargue inicial pone el bloque del fin del viaje (H10)"})
    assert corr_seg >= 0.998, corr_seg
    assert 0.85 * ref_total <= total <= ref_total, (total, ref_total)       # H6: viajes sin fecha de fin
    assert salidas == ref_salidas
