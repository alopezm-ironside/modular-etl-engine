# Modelo de datos

## Arquitectura medallion

El motor organiza los datos según el patrón **medallion** (Bronze → Silver →
Gold), que mejora progresivamente la estructura y calidad de los datos a medida
que fluyen entre capas.

| Capa       | Qué es                                                    | Foco                                                                 |
| ---------- | --------------------------------------------------------- | -------------------------------------------------------------------- |
| **Bronze** | Datos del origen "as-is" + metadata de ingesta            | Archivo histórico, linaje, auditoría, reproceso sin releer el origen |
| **Silver** | Limpios, conformados y **no duplicados** ("just-enough")  | Vista por entidad, self-service analytics, ad-hoc                    |
| **Gold**   | De-normalizado, read-optimized (star schema / data marts) | Presentación para reporting de proyectos específicos                 |

**Alcance del motor: produce Bronze y Silver.** Gold es modelado downstream y
opcional (ver más abajo). Por cada entidad de dominio se materializan dos tablas:
una Bronze y una Silver.

## Capa Bronze — append inmutable

Aterriza los datos tal como llegan del origen, más columnas de metadata de
ingesta. Registra **cada sincronización**: nunca se actualiza ni se borra, solo se
agregan filas. Una misma entidad de origen puede aparecer múltiples veces, una por
cada corrida que la haya tocado.

Su valor: historial frío, linaje, auditoría y la capacidad de **recrear las capas
superiores desde la fuente cruda en cualquier momento**, sin volver a leer el
sistema de origen.

Columnas de metadata presentes en cada fila:

| Columna         | Significado                                             |
| --------------- | ------------------------------------------------------- |
| `synced_at`     | Timestamp de ingesta de esa versión (load date/time)    |
| `sync_batch_id` | Identificador de la corrida que la insertó (process ID) |

Estas columnas solo tienen sentido en un modelo versionado: son la base de la
deduplicación hacia Silver y de la trazabilidad de cada dato hasta su corrida.

**Particionado y clustering** (ejemplo, `account_moves`):

- Partición por `date` (mensual).
- Clustering por `partner_name`, `move_type`, `state`.
- `require_partition_filter = true`: toda consulta debe filtrar por partición,
  para acotar costo y escaneo.

## Capa Silver — limpia, conformada y no duplicada

Una fila por entidad: la **versión más reciente** según `synced_at`. Aplica una
transformación "just-enough" (deduplicación) sobre Bronze para entregar una vista
estable de la entidad, sin que el consumidor deba entender el modelo de versionado
de la capa cruda.

> Es una Silver por fuente: deduplica `account.move` de Odoo. El conformado
> multi-fuente ("enterprise view": maestros de clientes unificados entre sistemas)
> es un paso posterior fuera del alcance de un job de ingesta única.

### Deduplicación: de Bronze a Silver

Silver se produce con el proyecto dbt `transform/` (ver
[`transform/README.md`](../../transform/README.md)). La lógica de deduplicación
está encapsulada en el macro `dedup_latest(relation, unique_key, order_by)`:
retiene una fila por `id`, la más reciente según `source_modified_at DESC,
ingested_at DESC` (SCD Type 1). La implementación usa `ROW_NUMBER()` vía subquery
— no `QUALIFY` — para garantizar compatibilidad incondicionanal con ZetaSQL en
contexto paramétrico de macro.

El predicado `where date is not null` en cada modelo satisface el
`require_partition_filter = true` de las tablas Bronze durante el rescan completo.

Silver se **materializa** (no es una vista que recalcule en cada consulta), porque
las herramientas de BI ejecutan consultas repetidas y la ventana sobre la tabla
Bronze completa sería costosa. Al derivarse de Bronze, es **reproducible** en
cualquier momento con `dbt build --full-refresh`.

## Capa Gold — downstream y opcional

Gold es la capa de presentación: modelos de-normalizados, star schemas o data
marts orientados a proyectos de reporting concretos. **No la produce este motor.**
Es modelado que depende de preguntas de negocio específicas y se construye
downstream (en BigQuery o con una herramienta como dbt) por analistas y data
engineers a partir de Silver.

Se justifica cuando aparece reporting curado o multi-fuente. Para análisis
operacional o ad-hoc de una sola fuente, consumir Silver directamente es
suficiente y habitual.

## Plano de control

Una tabla transversal a todos los módulos registra la metadata de cada
sincronización:

`<BQ_DATASET_CONTROL>.sync_metadata` — una fila por corrida: módulo, tipo,
inicio/fin, estado (`running` / `success` / `failed`), watermark
(`last_processed_id`), conteos de registros, llamadas a APIs y mensaje de error.
Es la fuente del watermark y la base de observabilidad de las ejecuciones.

> `control` es el token simbólico del ORM. En tiempo de ejecución se resuelve al
> valor de `BQ_DATASET_CONTROL` vía `schema_translate_map`. El nombre real del
> dataset lo define el IaC y se inyecta como variable de entorno.

## Organización en datasets de BigQuery

| Dataset (nombre real) | Capa | Variable de entorno | Propietario |
| --------------------- | ---- | ------------------- | ----------- |
| p. ej. `datalake_odoo_raw` | Bronze (append) | `BQ_DATASET_RAW` | IaC |
| p. ej. `datalake_silver` | Silver (deduplicada, dbt) | `BQ_DATASET_SILVER` | IaC (pendiente Slice 3) |
| p. ej. `datalake_control` | Plano de control (`sync_metadata`) | `BQ_DATASET_CONTROL` | IaC |

> Los datasets son provistos por el IaC. La aplicación de ingesta **no los crea**.
> El conector `BigQueryConnection` recibe los nombres reales vía `BQ_DATASET_RAW`
> y `BQ_DATASET_CONTROL` y aplica `schema_translate_map` en tiempo de ejecución.
> Los modelos ORM usan los tokens simbólicos (`"raw"`, `"control"`) en
> `__table_args__`; SQLAlchemy sustituye el token por el nombre real del dataset
> al construir las consultas.

> El proyecto dbt recibe `BQ_DATASET_SILVER` como variable de entorno (ver
> `transform/profiles.yml`). El provisioning del dataset en Terraform es parte de
> Slice 3. **Todos los datasets deben estar en la misma location de BigQuery** —
> BigQuery no permite queries cross-location.

## Consumo desde BI

La herramienta de BI (Metabase está fuertemente considerada) se conecta a la capa
**Silver** (o a Gold, cuando exista). Ventajas de este límite:

- El analista consulta tablas estables, una fila por entidad, sin lógica de
  deduplicación.
- Bronze queda libre para auditoría, reprocesamiento e historial sin afectar a los
  consumidores.
- El versionado y la resiliencia del pipeline (reprocesos, reintentos) son
  invisibles para el consumo: solo ve el estado actual limpio.
