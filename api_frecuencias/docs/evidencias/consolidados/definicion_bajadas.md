# Definición de bajadas en el histórico (§6.1 «Bajadas: descensos consolidados»)

Generado 2026-11-13T18:54:21-05:00 con `python -m scripts.contraste_consolidados` sobre la réplica local, en solo lectura (lector_ia), en el solape de timbradas_segmentos (2023-01-01 a 2023-02-27).

| idruta | Viajes válidos | Con timbradas | Sin numerobajadas | Σ bajadas segmentos (mismos viajes) | Σ numerobajadas (mismos viajes) | Diferencia | Σ numerobajadas (todos) | Diferencia total |
|---|---|---|---|---|---|---|---|---|
| 2 | 7.880 | 7.369 | 61 | 580.964 | 580.384 | 0,1 % | 622.730 | -6,7 % |
| 16 | 15.553 | 14.857 | 127 | 1.255.587 | 1.253.762 | 0,1 % | 1.309.586 | -4,1 % |
| 21 | 4.876 | 4.554 | 27 | 365.776 | 365.700 | 0,0 % | 393.129 | -7,0 % |
| Total | 28.309 | 26.780 | 215 | 2.202.327 | 2.199.846 | 0,1 % | 2.325.445 | -5,3 % |

- En los mismos viajes, las bajadas de los segmentos y numerobajadas difieren 0,1 %: miden lo mismo.
- En total difieren -5,3 %: la diferencia es de cobertura (viajes válidos sin timbradas), como la de pasajeros (definicion_pasajeros.md).
- Decisión (aplicada en la migración 0013): el histórico guarda bajadas_viajes = Σ numerobajadas de los viajes válidos (dato <= 300, ceros incluidos), la definición de pasajeros, que cubre todo 2023-2025 y es la que usan ALT-008, su backtest y el contraste con timbradas_consolidado; las bajadas y subidas de los segmentos quedan también en el histórico (columnas bajadas, subidas y viajes_con_timbradas).
