# transform — Capa Silver (dbt)

Proyecto dbt que produce la **capa Silver** del medallion: una fila por entidad,
estado actual, deduplicada desde Bronze. Vive en `transform/`, **fuera del
workspace de uv** — dbt no es un paquete Python del monorepo.

Adaptador: `dbt-bigquery` (dbt-fusion 2.0).

---

## Convención de modelos: mirror mecánico

Los modelos de staging son un **mirror mecánico de Bronze**: replican las
columnas de negocio con sus nombres de origen (`name`, `date`, `amount_total`,
etc.) y sólo conforman las columnas de auditoría/plomería:

| Columna Bronze | Columna Silver | Semántica |
|----------------|----------------|-----------|
| `write_date`   | `source_modified_at` | Timestamp de modificación en el origen |
| `synced_at`    | `ingested_at`        | Timestamp de ingesta en Bronze |

El conformado semántico (entidades de negocio agnósticas del origen, maestros
multi-fuente) queda diferido a una capa de consumo futura. Esta decisión mantiene
staging SAP-ready: agregar `stg_sap__...` no requiere tocar los modelos de Odoo.

### Naming

```
models/staging/<fuente>/stg_<fuente>__<entidad>.sql
```

Modelos actuales:

| Modelo | Entidad Bronze |
|--------|---------------|
| `stg_odoo__account_moves` | `account_moves` (cabeceras de asientos) |
| `stg_odoo__account_move_lines` | `account_move_lines` (líneas de asientos) |

---

## Macro `dedup_latest`

Reutilizable. Devuelve una fila por `unique_key`, la que ordena primero por
`order_by` (DESC = última gana).

```sql
{{ dedup_latest(
    relation   = 'bronze',
    unique_key = 'id',
    order_by   = 'source_modified_at desc, ingested_at desc'
) }}
```

Implementación: subquery `ROW_NUMBER()`, **no** `QUALIFY`. Razón: `QUALIFY` en
ZetaSQL requiere un `WHERE TRUE` de acompañamiento cuando el outer query no tiene
cláusula `WHERE`, lo que lo hace propenso a errores en un contexto paramétrico de
macro. La forma de subquery es válida incondicionalmente.

Comportamiento en casos borde:
- `write_date` NULL (filas pre-Slice 1): BigQuery ordena `NULLS LAST` en `DESC`;
  el tiebreak cae sobre `ingested_at DESC`.
- Dos snapshots con igual `write_date`: gana el `ingested_at` mayor.

---

## Materialización: `table` con swap path a `incremental`

**Estado actual (Slice 2):** `materialized='table'` — rescan completo + dedup en
cada ejecución. Elegido porque el volumen de `account.move`/`account.move.line`
es una fracción pequeña de la base Odoo.

**Swap path a `incremental` (Slice 3+, no implementar aquí):**

1. Cambiar config: `materialized='incremental'`, `incremental_strategy='merge'`,
   `unique_key='id'`.
2. Agregar en el CTE `bronze`, tras `where date is not null`:
   ```sql
   {% if is_incremental() %}
     and synced_at >= (
       select coalesce(max(ingested_at), timestamp('1970-01-01'))
       from {{ this }}
     )
   {% endif %}
   ```
   El eje de filtro es la **ingesta** (`synced_at`/`ingested_at`), no la fecha
   contable. Una entidad mutada re-entra en Bronze con un nuevo `synced_at`
   independientemente de su `date` original.
3. Programar `dbt build --full-refresh` periódico para corrección de deriva.
4. El macro `dedup_latest` no se modifica.

---

## Cómo ejecutar

### Requisitos previos

Autenticación con ADC:

```bash
gcloud auth application-default login
```

### Variables de entorno

| Variable | Requerida | Default | Descripción |
|----------|-----------|---------|-------------|
| `BQ_PROJECT_ID` | Sí | — | Proyecto GCP |
| `BQ_DATASET_RAW` | Sí | — | Dataset Bronze (fuente) |
| `BQ_DATASET_SILVER` | Sí | `datalake_silver` | Dataset Silver (destino) |
| `BQ_LOCATION` | No | `us-central1` | Location de BigQuery |
| `DBT_TARGET` | No | `dev` | Target de dbt |
| `DBT_BQ_METHOD` | No | `oauth` | Método de auth BigQuery |
| `DBT_THREADS` | No | `4` | Paralelismo |
| `DBT_PROFILES_DIR` | No | `transform/` | Directorio de `profiles.yml` |

### Ejecutar

```bash
cd transform
dbt build          # modelos + schema tests + unit tests
dbt build --select stg_odoo__account_moves   # un modelo
dbt build --full-refresh                     # rescan forzado (swap path)
```

> **Unit tests**: los unit tests requieren que las tablas source de Bronze existan
> en el warehouse — dbt infiere los tipos de columna desde ellas.

---

## Requisito de location única (crítico)

Todos los datasets de BigQuery involucrados (`BQ_DATASET_RAW`, `BQ_DATASET_SILVER`,
y `BQ_DATASET_CONTROL` del job de ingesta) **deben estar en la misma location**.
BigQuery no permite queries cross-location; una query que cruce locations fallará
con un error de tiempo de ejecución. Asegurarse en el IaC antes del primer deploy.

---

## Tests

| Tipo | Cobertura |
|------|-----------|
| Schema `unique` + `not_null` sobre `id` | Ambos modelos |
| Unit: latest por `write_date` | `stg_odoo__account_moves`, `stg_odoo__account_move_lines` |
| Unit: tiebreak por `synced_at` (mismo `write_date`) | Ambos modelos |
| Unit: fallback con `write_date` NULL (filas pre-Slice 2) | `stg_odoo__account_move_lines` |

---

## Alcance de Slice 2

**Incluido:**
- Proyecto dbt `transform/` con modelos staging y macro `dedup_latest`.
- Tests de schema y unit tests.

**Fuera de scope (Slice 3):**
- Provisioning del dataset Silver en Terraform.
- Orquestación Bronze → dbt (trigger post-job de ingesta).
- Gate `dbt build` en CI.
- Imagen Docker y WIF para el job dbt en Cloud Run.
