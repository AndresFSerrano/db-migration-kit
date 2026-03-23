from pathlib import Path

from db_migration_kit.inspector import ProjectInspection
from db_migration_kit.scaffold import initialize_project_scaffold, initialize_project_scaffold_from_inspection


def test_initialize_project_scaffold_creates_expected_files(tmp_path: Path) -> None:
    created = initialize_project_scaffold(tmp_path, project_name="sample-project")

    created_paths = {path.relative_to(tmp_path).as_posix() for path in created}
    assert "migration_project.py" in created_paths
    assert "migrations/alembic.ini" in created_paths
    assert "migrations/env.py" in created_paths
    assert "migrations/script.py.mako" in created_paths
    assert (tmp_path / "migrations" / "versions").exists()


def test_initialize_project_scaffold_from_inspection_generates_settings_aware_project_module(tmp_path: Path) -> None:
    inspection = ProjectInspection(
        root=str(tmp_path),
        project_name="sample-project",
        suggested_provider_name="sqlalchemy-postgres",
        suggested_schema_source="persistence-kit-registry",
        registry_initializer_import_path="app.infrastructure.repository_factory.register_defaults:register_defaults",
        settings_getter_import_path="app.core.config:get_settings",
    )

    initialize_project_scaffold_from_inspection(tmp_path, inspection=inspection)

    migration_project = (tmp_path / "migration_project.py").read_text(encoding="utf-8")
    env_py = (tmp_path / "migrations" / "env.py").read_text(encoding="utf-8")

    assert "from app.core.config import get_settings" in migration_project
    assert '_read_env_value("MIGRATION_DATABASE_URL")' in migration_project
    assert '_read_env_value("MIGRATION_SYNC_DATABASE_URL")' in migration_project
    assert '_read_env_value("POSTGRES_PORT_HOST")' in migration_project
    assert "def _resolve_postgres_target" in migration_project
    assert "PersistenceKitRegistrySchemaSource" in migration_project
    assert "fileConfig(config.config_file_name)" in env_py
    assert "except KeyError:" in env_py
