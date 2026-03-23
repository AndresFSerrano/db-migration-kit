from pathlib import Path

from db_migration_kit.bootstrap import bootstrap_project
from db_migration_kit.inspector import inspect_project


def test_inspect_project_detects_registry_and_postgres(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.poetry]
name = "demo_app"
[tool.poetry.dependencies]
python = "^3.11"
asyncpg = "^0.30.0"
persistence-kit = "2.0.0"
""".strip(),
        encoding="utf-8",
    )
    registry_path = tmp_path / "app" / "infrastructure" / "repository_factory"
    registry_path.mkdir(parents=True)
    (registry_path / "register_defaults.py").write_text("def register_defaults():\n    return None\n", encoding="utf-8")

    inspection = inspect_project(tmp_path)

    assert inspection.project_name == "demo-app"
    assert inspection.suggested_provider_name == "sqlalchemy-postgres"
    assert inspection.suggested_schema_source == "persistence-kit-registry"
    assert inspection.registry_initializer_import_path == "app.infrastructure.repository_factory.register_defaults:register_defaults"


def test_bootstrap_project_generates_files_from_inspection(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.poetry]
name = "demo_app"
[tool.poetry.dependencies]
python = "^3.11"
persistence-kit = "2.0.0"
""".strip(),
        encoding="utf-8",
    )
    registry_path = tmp_path / "app" / "infrastructure" / "repository_factory"
    registry_path.mkdir(parents=True)
    (registry_path / "register_defaults.py").write_text("def register_defaults():\n    return None\n", encoding="utf-8")

    inspection, created = bootstrap_project(tmp_path)

    assert inspection.suggested_schema_source == "persistence-kit-registry"
    created_names = {path.relative_to(tmp_path).as_posix() for path in created}
    assert "migration_project.py" in created_names
    migration_project = (tmp_path / "migration_project.py").read_text(encoding="utf-8")
    assert "PersistenceKitRegistrySchemaSource" in migration_project
    assert "app.infrastructure.repository_factory.register_defaults:register_defaults" in migration_project
