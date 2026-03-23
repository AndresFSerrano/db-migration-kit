# db_migration_kit

Kit reutilizable para revisar y ejecutar migraciones de esquema de base de datos en proyectos Python.

## Objetivo

Este paquete busca separar tres responsabilidades:

- describir el esquema deseado
- revisar el impacto antes de aplicarlo
- ejecutar migraciones de forma controlada

La idea central es que el flujo normal no sea `aplicar y ya`, sino:

1. `synth`: sintetizar el estado deseado
2. `diff`: comparar estado actual vs. estado deseado
3. `review`: explicar qué cambia
4. `upgrade`: aplicar cambios aceptados

## Principios

- reutilizable entre proyectos
- documentación y salida orientadas a revisión humana
- desacoplado del arranque de la aplicación
- desacoplado de un motor específico
- extensible mediante providers

## Providers

El kit no asume una base de datos concreta.

Cada proyecto utiliza un provider que conoce:

- cómo inspeccionar el esquema actual
- cómo construir el esquema deseado
- cómo calcular diferencias
- cómo ejecutar migraciones para ese backend

Providers disponibles en esta versión:

- `sqlalchemy-sqlite`
- `sqlalchemy-postgres`

Ambos comparten una base común en SQLAlchemy y Alembic, pero el comportamiento de inspección puede variar por dialecto. Por ejemplo, `postgres` permite revisar enums nativos con más precisión que `sqlite`.

## Flujo local

```bash
poetry run python -m db_migration_kit.cli inspect-project --root .
poetry run python -m db_migration_kit.cli bootstrap --root .
poetry run python -m db_migration_kit.cli doctor --project-module migration_project
poetry run python -m db_migration_kit.cli review --project-module migration_project
poetry run python -m db_migration_kit.cli diff --project-module migration_project
```

## Flujo generico de integracion

Para integrar el kit en un proyecto Python como paquete publicado:

1. instalar `db-migration-kit` desde PyPI
2. correr `inspect-project` para detectar provider, source y puntos de integracion
3. correr `bootstrap` para generar `migration_project.py` y `migrations/*`
4. revisar el `migration_project.py` generado y confirmar la forma correcta de construir la URL de la base
5. correr `doctor` para validar que el proyecto de migracion es cargable
6. correr `review` y `diff` contra una base real

Ejemplo de instalacion:

```bash
poetry add db-migration-kit
```

Comandos base:

```bash
poetry run python -m db_migration_kit.cli inspect-project --root .
poetry run python -m db_migration_kit.cli bootstrap --root .
poetry run python -m db_migration_kit.cli doctor --project-module migration_project
poetry run python -m db_migration_kit.cli review --project-module migration_project
poetry run python -m db_migration_kit.cli diff --project-module migration_project
```

## Como leer el resultado

El kit no usa una sola categoria de cambio.

Lecturas principales:

- `agregar`, `modificar`, `eliminar`: drift real entre la base y el esquema deseado
- `riesgo`: el kit detecto un caso ambiguo que requiere revision manual
- `pendiente`: diferencia esperable pero todavia no materializada

En proyectos con `persistence_kit`, una tabla puede aparecer como:

- `pendiente / tabla-lazy`: el repositorio esta registrado y forma parte del esquema deseado, pero la tabla aun no existe fisicamente porque `persistence_kit` la crea de forma lazy en el primer uso

Eso no debe interpretarse automaticamente como una migracion obligatoria.

## Primera snapshot

La primera snapshot no significa necesariamente "aplicar cambios ya". Significa capturar una linea base entendible del proyecto.

El flujo recomendado para una primera snapshot es:

1. levantar una base controlada del proyecto
2. correr `review`
3. separar hallazgos en tres grupos:
   - drift real
   - objetos legacy
   - materializacion lazy pendiente
4. usar `diff` como salida estructurada de esa primera linea base

Ejemplo:

```bash
poetry run python -m db_migration_kit.cli review --project-module migration_project
poetry run python -m db_migration_kit.cli diff --project-module migration_project
```

Si el resultado contiene solo `pendiente / tabla-lazy`, la lectura correcta es:

- el esquema deseado ya quedo bien identificado
- no hay drift duro relevante
- solo faltan tablas que el sistema crea cuando realmente usa esos repositorios

## Recomendacion para proyectos con persistence_kit

Si el proyecto usa `persistence_kit`, la expectativa correcta es:

- el schema source describe lo que deberia existir segun `register_entity`
- la base puede no tener aun todas las tablas si algunos repositorios nunca se han usado
- `review` no deberia forzar a cambiar ese comportamiento

Por eso el kit distingue entre:

- drift estructural real
- materializacion lazy pendiente

La primera snapshot debe preservar esa distincion, no borrarla.

## Snapshots versionadas

El kit guarda snapshots versionadas por proyecto en:

```text
migrations/snapshots/
```

Esa ruta se deriva automaticamente desde `migrations_dir`, asi que el kit sabe siempre donde buscarlas.

Comandos:

```bash
poetry run python -m db_migration_kit.cli snapshot-create --project-module migration_project
poetry run python -m db_migration_kit.cli snapshot-create --project-module migration_project --label baseline
poetry run python -m db_migration_kit.cli snapshot-list --project-module migration_project
poetry run python -m db_migration_kit.cli snapshot-show --project-module migration_project --version-id v001
poetry run python -m db_migration_kit.cli snapshot-delete --project-module migration_project --version-id v001
poetry run python -m db_migration_kit.cli snapshot-apply --project-module migration_project --version-id v001
poetry run python -m db_migration_kit.cli snapshot-rollback --project-module migration_project --version-id v001
```

Convencion:

- `v001`, `v002`, `v003`: snapshots secuenciales
- `v001-baseline`, `v002-post-auth`: snapshots con etiqueta opcional

Cada snapshot guarda:

- `review`
- `diff`
- `desired_snapshot`
- `alembic_revision`
- metadatos de proyecto, provider, fecha y version

### Como crear la primera snapshot

Si ya validaste el proyecto con `doctor`, la primera snapshot versionada se crea asi:

```bash
poetry run python -m db_migration_kit.cli snapshot-create --project-module migration_project --label baseline
```

Luego puedes listar y revisar:

```bash
poetry run python -m db_migration_kit.cli snapshot-list --project-module migration_project
poetry run python -m db_migration_kit.cli snapshot-show --project-module migration_project --version-id v001-baseline
```

La primera snapshot no reemplaza `review` ni `diff`. Los conserva como baseline versionado.

## Aplicar una snapshot

Si el proyecto ya tiene revisiones Alembic reales, el kit puede aplicar o volver a una snapshot usando la revision asociada guardada dentro de la snapshot.

Comandos:

```bash
poetry run python -m db_migration_kit.cli snapshot-apply --project-module migration_project --version-id v003
poetry run python -m db_migration_kit.cli snapshot-rollback --project-module migration_project --version-id v001-baseline
```

Semantica:

- `snapshot-apply`: mueve la base a la revision Alembic asociada a la snapshot elegida
- `snapshot-rollback`: usa la misma resolucion pero con intencion semantica de volver a una version anterior

El usuario trabaja con snapshots. Alembic se usa por detras como motor de upgrade/downgrade.

## Que significa que una snapshot sea "ejecutable"

Una snapshot puede estar en dos estados:

- semantica: describe el esquema esperado, pero no tiene una revision Alembic asociada distinta
- ejecutable: tiene una `alembic_revision` real y el kit puede mover la base hacia esa version usando `snapshot-apply` o `snapshot-rollback`

Ejemplo:

- `v001-baseline -> alembic_revision = base`
- `v002-after-phone -> alembic_revision = c3afdddecb7e`

En ese escenario:

- `v001-baseline` describe el baseline inicial
- `v002-after-phone` ya representa una version ejecutable del esquema

## Flujo recomendado para crear una primera version ejecutable

1. integrar el kit
2. validar el proyecto con `doctor`
3. revisar el estado actual con `review` y `diff`
4. crear la baseline inicial
5. introducir un cambio real de esquema en una entidad ya materializada
6. volver a correr `review` y `diff`
7. crear una nueva snapshot
8. dejar que el kit genere una revision Alembic y la asocie a esa snapshot
9. aplicar esa snapshot con `snapshot-apply`

Comandos tipicos:

```bash
poetry run python -m db_migration_kit.cli snapshot-create --project-module migration_project --label baseline
poetry run python -m db_migration_kit.cli review --project-module migration_project
poetry run python -m db_migration_kit.cli diff --project-module migration_project
poetry run python -m db_migration_kit.cli snapshot-create --project-module migration_project --label after-change
poetry run python -m db_migration_kit.cli snapshot-list --project-module migration_project
poetry run python -m db_migration_kit.cli snapshot-apply --project-module migration_project --version-id v002-after-change
```

## Como interpretar review y diff

El significado operativo de la salida es:

- `agregar`, `modificar`, `eliminar`: drift real o cambio de esquema aplicable
- `pendiente / tabla-lazy`: el esquema deseado incluye esa tabla, pero el proyecto la materializa lazy y todavia no existe fisicamente
- `riesgo`: el kit detecto algo ambiguo y requiere revision manual

Entonces:

- si `review` queda vacio, la base esta alineada con el esquema deseado
- si solo queda `pendiente / tabla-lazy`, la base esta alineada salvo la materializacion lazy esperada
- si hay `agregar/modificar/eliminar`, existe drift o cambio real de esquema

## Modo de trabajo en desarrollo local

Si estas desarrollando el kit mismo, puedes iterar localmente antes de publicar una nueva version:

1. actualizar el codigo del paquete
2. reconstruir o reinstalar el entorno local del proyecto consumidor
3. usar snapshots para versionar el estado esperado
4. usar `snapshot-apply` para probar upgrades reales

## Modo de trabajo en un entorno persistente

Si el entorno tiene datos y no debe reiniciarse desde cero:

- no destruir volumenes como rutina
- crear una snapshot antes de actualizar codigo
- hacer pull del codigo
- reconstruir imagen
- revisar `review/diff`
- aplicar la snapshot objetivo
- volver a validar el esquema

Secuencia recomendada:

```bash
poetry run python -m db_migration_kit.cli snapshot-create --project-module migration_project --label pre-pull
git pull
poetry install
poetry run python -m db_migration_kit.cli review --project-module migration_project
poetry run python -m db_migration_kit.cli diff --project-module migration_project
poetry run python -m db_migration_kit.cli snapshot-apply --project-module migration_project --version-id <objetivo>
poetry run python -m db_migration_kit.cli review --project-module migration_project
```

## Integracion con CI/CD

El kit puede integrarse en CI/CD de dos formas:

1. validacion
- correr `doctor`
- correr `diff`
- fallar si hay drift real inesperado

2. despliegue controlado
- aplicar una snapshot ejecutable
- validar con `review`
- desplegar la aplicacion solo si el esquema queda alineado

Ejemplo de validacion:

```bash
python -m db_migration_kit.cli doctor --project-module migration_project
python -m db_migration_kit.cli diff --project-module migration_project
```

Ejemplo de despliegue:

```bash
python -m db_migration_kit.cli snapshot-apply --project-module migration_project --version-id v003-release
python -m db_migration_kit.cli review --project-module migration_project
```

## Limites actuales

El kit ya puede:

- inspeccionar el esquema actual
- sintetizar el esquema deseado
- generar snapshots versionadas
- asociar snapshots con revisiones Alembic
- aplicar snapshots usando Alembic por detras

Pero aun hay que revisar manualmente:

- cambios destructivos delicados
- migraciones de datos
- cambios que requieren backfill
- escenarios no lineales de ramas Alembic

## Estructura mínima por proyecto

Cada proyecto solo necesita:

- una carpeta de migraciones
- un archivo `migration_project.py`
- un objeto `project` que implemente el contrato de `MigrationProject`

El kit puede generar estos archivos automáticamente a partir de un escaneo inicial del proyecto.

## Estado actual

La versión actual deja listo:

- contrato de provider
- snapshots y diff de esquema
- revisión de columnas, índices, foreign keys y enums
- detección básica de posibles renombres
- inspección inicial del proyecto
- bootstrap automático de archivos mínimos
- runner reusable
- scaffold inicial
- comandos `synth`, `diff`, `review`, `upgrade`, `downgrade`, `stamp`

La parte de migraciones reales puede crecer por provider sin acoplar el kit a un proyecto particular.
