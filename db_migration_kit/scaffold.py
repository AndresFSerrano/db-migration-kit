from __future__ import annotations

from pathlib import Path

from db_migration_kit.inspector import ProjectInspection


def _render_alembic_ini(project_name: str) -> str:
    return (
        "[alembic]\n"
        "script_location = migrations\n"
        "prepend_sys_path = .\n"
        "version_path_separator = os\n"
        "sqlalchemy.url = driver://reemplazar\n"
        f"# project = {project_name}\n"
    )


def _render_env_py() -> str:
    return """from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except KeyError:
        pass

target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
"""


def _render_script_template() -> str:
    return '''"""${message}"""

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
'''


def _render_project_module(
    class_name: str,
    project_name: str,
    *,
    provider_name: str,
    schema_source: str,
    registry_initializer_import_path: str | None,
    metadata_import_path: str | None,
    settings_getter_import_path: str | None,
) -> str:
    schema_source_body = "        return super().get_schema_source()"
    if schema_source == "persistence-kit-registry" and registry_initializer_import_path:
        schema_source_body = (
            "        return PersistenceKitRegistrySchemaSource(\n"
            f'            registry_initializer_import_path="{registry_initializer_import_path}"\n'
            "        )"
        )
    imports = [
        "from db_migration_kit import MigrationProject, MigrationProjectSettings",
    ]
    if schema_source == "persistence-kit-registry" and registry_initializer_import_path:
        imports.append("from db_migration_kit.sources.persistence_kit_registry import PersistenceKitRegistrySchemaSource")
    settings_helper_block = ""
    database_url_expr = 'os.environ["DATABASE_URL"]'
    sync_database_url_expr = 'os.environ.get("SYNC_DATABASE_URL")'
    if settings_getter_import_path:
        module_path, _, attribute = settings_getter_import_path.partition(":")
        imports.append(f"from {module_path} import {attribute}")
        settings_helper_block = f"""

def _read_env_value(name: str) -> str | None:
    env_value = os.environ.get(name)
    if env_value:
        return env_value
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return None
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip("'").strip('"')
    return None


def _build_async_database_url() -> str:
    direct_url = _read_env_value("MIGRATION_DATABASE_URL") or _read_env_value("DATABASE_URL")
    if direct_url:
        return direct_url
    settings = {attribute}()
    postgres_dsn = getattr(settings, "postgres_dsn", None)
    if postgres_dsn:
        return postgres_dsn
    postgres_host, postgres_port = _resolve_postgres_target(settings.postgres_host, settings.postgres_port)
    return (
        f"postgresql+asyncpg://{{settings.postgres_user}}:{{settings.postgres_password}}"
        f"@{{postgres_host}}:{{postgres_port}}/{{settings.postgres_db}}"
    )


def _build_sync_database_url() -> str | None:
    direct_url = _read_env_value("MIGRATION_SYNC_DATABASE_URL") or _read_env_value("SYNC_DATABASE_URL")
    if direct_url:
        return direct_url
    async_url = _build_async_database_url()
    if async_url.startswith("postgresql+asyncpg://"):
        return async_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    return async_url


def _resolve_postgres_target(host: str | None, port: int | None) -> tuple[str | None, int | None]:
    if host != "postgres":
        return host, port
    try:
        import socket
        socket.getaddrinfo(host, None)
        return host, port
    except OSError:
        host_port = _read_env_value("POSTGRES_PORT_HOST")
        resolved_port = int(host_port) if host_port else port
        return "localhost", resolved_port
"""
        database_url_expr = "_build_async_database_url()"
        sync_database_url_expr = "_build_sync_database_url()"
    imports_text = "\n".join(imports)
    metadata_line = (
        f'metadata_import_path=os.environ.get("MIGRATION_METADATA_IMPORT", "{metadata_import_path}"),'
        if metadata_import_path
        else 'metadata_import_path=os.environ.get("MIGRATION_METADATA_IMPORT"),'
    )
    return f"""from __future__ import annotations

import os
from pathlib import Path

{imports_text}
{settings_helper_block}


class {class_name}(MigrationProject):
    def get_settings(self) -> MigrationProjectSettings:
        return MigrationProjectSettings(
            project_name="{project_name}",
            migrations_dir=Path(__file__).resolve().parent / "migrations",
            database_url={database_url_expr},
            sync_database_url={sync_database_url_expr},
            provider_name=os.environ.get("MIGRATION_PROVIDER", "{provider_name}"),
            {metadata_line}
        )

    def get_schema_source(self):
{schema_source_body}


project = {class_name}()
"""


def initialize_project_scaffold(root: Path, *, project_name: str, class_name: str = "ProjectMigration") -> list[Path]:
    inspection = ProjectInspection(
        root=str(root.resolve()),
        project_name=project_name,
        suggested_provider_name="sqlalchemy-sqlite",
        suggested_schema_source="sqlalchemy-metadata",
    )
    return initialize_project_scaffold_from_inspection(root, inspection=inspection, class_name=class_name)


def initialize_project_scaffold_from_inspection(
    root: Path,
    *,
    inspection: ProjectInspection,
    class_name: str = "ProjectMigration",
) -> list[Path]:
    migrations_dir = root / "migrations"
    versions_dir = migrations_dir / "versions"
    created: list[Path] = []
    for path in (migrations_dir, versions_dir):
        path.mkdir(parents=True, exist_ok=True)

    files_to_write = {
        migrations_dir / "alembic.ini": _render_alembic_ini(inspection.project_name),
        migrations_dir / "env.py": _render_env_py(),
        migrations_dir / "script.py.mako": _render_script_template(),
        root / "migration_project.py": _render_project_module(
            class_name,
            inspection.project_name,
            provider_name=inspection.suggested_provider_name,
            schema_source=inspection.suggested_schema_source,
            registry_initializer_import_path=inspection.registry_initializer_import_path,
            metadata_import_path=inspection.metadata_import_path,
            settings_getter_import_path=inspection.settings_getter_import_path,
        ),
    }
    for path, content in files_to_write.items():
        if path.exists():
            continue
        path.write_text(content, encoding="utf-8")
        created.append(path)
    return created
