-- =============================================
-- TABLA 1: Porciones base (~20 cm c/u)
-- =============================================
CREATE TABLE rutas_segmentos_porcion (
    id                 BIGSERIAL       PRIMARY KEY,
    idruta             INTEGER         NOT NULL,
    idrutageo          INTEGER         NOT NULL,
    nro_porcion        INTEGER         NOT NULL,
    inicio_m           NUMERIC(12, 3)  NOT NULL,
    fin_m              NUMERIC(12, 3)  NOT NULL,
    longitud_porcion_m NUMERIC(12, 3)  NOT NULL,
    punto_inicio       GEOMETRY(POINT, 4326),
    punto_fin          GEOMETRY(POINT, 4326),
    geom_porcion       GEOMETRY(LINESTRING, 4326),
    UNIQUE (idruta, idrutageo, nro_porcion)
);

-- =============================================
-- TABLA 2: Configuración de segmentación
-- =============================================
CREATE TABLE rutas_segmentos_config (
    id                  BIGSERIAL       PRIMARY KEY,
    idruta              INTEGER         NOT NULL,
    idrutageo           INTEGER         NOT NULL,
    tipo_agrupacion     VARCHAR(20)     NOT NULL
                            CHECK (tipo_agrupacion IN ('distancia', 'cantidad')),
    tamaño_segmento_m   NUMERIC(12, 3),   -- aplica cuando tipo = 'distancia'
    numero_segmentos    INTEGER,           -- aplica cuando tipo = 'cantidad'
    fecha_creacion      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    tamaño_porcion_m         NUMERIC(12, 4) NOT NULL DEFAULT 0.20,
    tamaño_minimo_porcion_m  NUMERIC(12, 4) NOT NULL DEFAULT 0.20;
    UNIQUE (idruta, idrutageo),
    CHECK (
        (tipo_agrupacion = 'distancia' AND tamaño_segmento_m IS NOT NULL AND numero_segmentos IS NULL)
        OR
        (tipo_agrupacion = 'cantidad'  AND numero_segmentos IS NOT NULL  AND tamaño_segmento_m IS NULL)
    )
);

-- =============================================
-- TABLA 3: Segmentos resultantes (relacional)
-- =============================================
CREATE TABLE rutas_segmentos (
    id               BIGSERIAL       PRIMARY KEY,
    id_config        BIGINT          NOT NULL
                         REFERENCES rutas_segmentos_config(id),
    idruta           INTEGER         NOT NULL,
    idrutageo        INTEGER         NOT NULL,
    nro_segmento     INTEGER         NOT NULL,
    activo           BOOLEAN         NOT NULL DEFAULT TRUE,
    porciones_ids    TEXT            NOT NULL,  -- ej: "[1,2,3,4,5]"
    longitud_m       NUMERIC(12, 3)  NOT NULL,
    geom_segmento    GEOMETRY(LINESTRING, 4326),
    UNIQUE (id_config, nro_segmento)
);

CREATE TABLE timbradas_segmentos (
    id_timbrada_segmento  BIGSERIAL  PRIMARY KEY,
    id_segmento           BIGINT     NOT NULL REFERENCES rutas_segmentos(id),
    id_viaje              BIGINT     NOT null references progvehiculos (idprogramacion),
    fecha                 DATE       NOT NULL,
    hora_inicio           TIME       NOT NULL,
    hora_fin              TIME       NOT NULL,
    subidas               INTEGER    NOT NULL DEFAULT 0,
    bajadas               INTEGER    NOT NULL DEFAULT 0,
    pasajeros             INTEGER    NOT NULL DEFAULT 0,
    ultimaactualizacion   timestamp  null,
    UNIQUE (id_segmento, id_viaje)
);


CREATE TABLE public.timbradas_segmentos_anio (
    id_timbrada_segmento_anio  BIGSERIAL       NOT NULL,
    id_segmento                BIGINT          NOT NULL,
    proceso                    VARCHAR(50)     NOT NULL,
    ano                        INT4            NOT NULL,
    id_ruta                    INT8            NOT NULL,
    id_dia_semana              INT4            NOT NULL,
    id_estacionalidad_anio     INT8            NOT NULL,
    hora                       TIME            NOT NULL,
    hora_inicio                TIME            NOT NULL,
    hora_fin                   TIME            NOT NULL,
    subidas                    INT4            NOT NULL,
    bajadas                    INT4            NOT NULL,
    pasajeros                  INT4            NOT NULL,
    nro_viajes                 INT4            NOT NULL,
    promedio_subidas           NUMERIC(10, 2)  NULL,
    promedio_bajadas           NUMERIC(10, 2)  NULL,
    promedio_pasajeros         NUMERIC(10, 2)  NULL,
    ultima_actualizacion       TIMESTAMP       NULL,
    CONSTRAINT pk_timbradas_segmentos_anio
        PRIMARY KEY (id_timbrada_segmento_anio),
    CONSTRAINT uq_timbradas_segmentos_anio_bloque
        UNIQUE (id_segmento, proceso, ano, id_ruta, id_dia_semana,
                id_estacionalidad_anio, hora, hora_inicio, hora_fin),
    CONSTRAINT fk_tsa_id_segmento
        FOREIGN KEY (id_segmento)
        REFERENCES public.rutas_segmentos(id),
    CONSTRAINT fk_tsa_id_dia_semana
        FOREIGN KEY (id_dia_semana)
        REFERENCES public.dias_semana(id_dia_semana),
    CONSTRAINT fk_tsa_id_estacionalidad_anio
        FOREIGN KEY (id_estacionalidad_anio)
        REFERENCES public.estacionalidades_anio(id_estacionalidad_anio)
);


CREATE TABLE timbradas_segmentos_anio_trazabilidad (
    id_trazabilidad              BIGSERIAL  PRIMARY KEY,
    id_timbrada_segmento_anio    BIGINT     NOT NULL REFERENCES timbradas_segmentos_anio(id_timbrada_segmento_anio),
    idprogramacion               BIGINT     NOT NULL,
    subidas                      INT        NOT NULL DEFAULT 0,
    bajadas                      INT        NOT NULL DEFAULT 0,
    pasajeros                    INT        NOT NULL DEFAULT 0,
    vigente                      BOOLEAN    NOT NULL DEFAULT TRUE
);


-- =====================================================================
-- DDL: timbradas_segmentos_consolidado
-- =====================================================================
CREATE TABLE public.timbradas_segmentos_consolidado (
    id_timbrada_segmentos_consolidado  BIGSERIAL       NOT NULL,
    id_segmento                        BIGINT          NOT NULL,
    proceso                            VARCHAR(50)     NOT NULL,
    id_ruta                            INT8            NOT NULL,
    id_dia_semana                      INT4            NOT NULL,
    id_estacionalidad                  INT8            NOT NULL,
    hora                               TIME            NOT NULL,
    hora_inicio                        TIME            NOT NULL,
    hora_fin                           TIME            NOT NULL,
    subidas                            INT4            NOT NULL,
    bajadas                            INT4            NOT NULL,
    pasajeros                          INT4            NOT NULL,
    nro_viajes                         INT4            NOT NULL,
    promedio_subidas                   NUMERIC(10, 2)  NULL,
    promedio_bajadas                   NUMERIC(10, 2)  NULL,
    promedio_pasajeros                 NUMERIC(10, 2)  NULL,
    ultima_actualizacion               TIMESTAMP       NULL,
    CONSTRAINT pk_timbradas_segmentos_consolidado
        PRIMARY KEY (id_timbrada_segmentos_consolidado),
    CONSTRAINT uk_timbradas_segmentos_consolidado_key
        UNIQUE (id_segmento, proceso, id_dia_semana, id_estacionalidad, hora, hora_inicio, hora_fin),
    CONSTRAINT fk_tsc_id_segmento
        FOREIGN KEY (id_segmento) REFERENCES public.rutas_segmentos(id),
    CONSTRAINT fk_tsc_id_dia_semana
        FOREIGN KEY (id_dia_semana) REFERENCES public.dias_semana(id_dia_semana),
    CONSTRAINT fk_tsc_id_estacionalidad
        FOREIGN KEY (id_estacionalidad) REFERENCES public.estacionalidades(id_estacionalidad)
);