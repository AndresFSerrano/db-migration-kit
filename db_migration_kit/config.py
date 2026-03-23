from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class MigrationProjectSettings:
    project_name: str
    migrations_dir: Path
    database_url: str
    provider_name: str = "sqlalchemy-sqlite"
    alembic_ini_path: Path | None = None
    metadata_import_path: str | None = None
    version_table: str = "alembic_version"
    sync_database_url: str | None = None

    def normalized_migrations_dir(self) -> Path:
        return self.migrations_dir.resolve()

    def normalized_alembic_ini_path(self) -> Path:
        if self.alembic_ini_path is not None:
            return self.alembic_ini_path.resolve()
        return (self.migrations_dir / "alembic.ini").resolve()

    def normalized_snapshots_dir(self) -> Path:
        return (self.migrations_dir / "snapshots").resolve()

    def validate(self) -> None:
        if not self.project_name.strip():
            raise ValueError("project_name es obligatorio")
        if not self.database_url.strip():
            raise ValueError("database_url es obligatorio")
        if not self.provider_name.strip():
            raise ValueError("provider_name es obligatorio")
