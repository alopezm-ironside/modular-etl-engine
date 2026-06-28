# datalake-platform

Plataforma de datos (medallion ELT) sobre BigQuery: ingesta datos de sistemas de
origen (Odoo, y por diseño cualquier otro) hacia una capa raw y los modela en
capas servidas listas para análisis de BI. Su motor de ingesta es modular y
agnóstico del origen y del destino.

Cada módulo de sincronización se empaqueta y despliega como un **Cloud Run Job**
independiente. La orquestación es agnóstica del origen y del destino: ejecutar
`Odoo → BigQuery`, `Odoo → Snowflake` o `SAP → BigQuery` no cambia el proceso,
solo los adaptadores inyectados.

## Estructura

```
datalake-platform/
├── pyproject.toml          # raíz del workspace uv (virtual)
├── packages/
│   └── common/             # etl-common: contratos, infraestructura, pipeline genérico
├── jobs/
│   └── account/            # etl-account: ETL de account.move (un Cloud Run Job)
└── transform/              # proyecto dbt — capa Silver (fuera del workspace uv)
```

- `packages/*` son **librerías** (se importan, no se ejecutan).
- `jobs/*` son **unidades desplegables** (cada una con su `Dockerfile`; una imagen → un Cloud Run Job).
- `transform/` es el **proyecto dbt** que produce la capa Silver. No forma parte del workspace de uv — dbt no es un paquete Python del monorepo.

## Requisitos

- Python 3.11
- [uv](https://docs.astral.sh/uv/)

## Desarrollo

```bash
uv sync --all-packages          # instala todo el workspace + grupo dev
uv run lefthook install         # activa los git hooks (una vez por clon)
uv run ruff check .             # lint
uv run mypy                     # type check
uv run pytest                   # tests

# Ejecutar un job localmente (requiere variables de entorno; ver .env.example)
uv run --package etl-account account-job
```

## Despliegue

El build se hace desde la **raíz del repositorio** (es el contexto del workspace):

```bash
docker build -f jobs/account/Dockerfile -t <registry>/account:<sha> .
```

La imagen se publica en Artifact Registry y un Cloud Run Job la referencia por
digest inmutable. La infraestructura como código vive en un repositorio separado.

## Documentación

- [`docs/architecture/README.md`](docs/architecture/README.md) — arquitectura del motor
- [`docs/architecture/data-model.md`](docs/architecture/data-model.md) — modelo de datos (medallion) y consumo BI
- [`docs/dev/adding-a-module.md`](docs/dev/adding-a-module.md) — cómo agregar un módulo nuevo
- [`transform/README.md`](transform/README.md) — proyecto dbt: capa Silver, convenciones, cómo ejecutar
