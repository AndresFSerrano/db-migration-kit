from __future__ import annotations

from typing import TYPE_CHECKING

from db_migration_kit.schema import SchemaDiff, SchemaSnapshot

if TYPE_CHECKING:
    from db_migration_kit.project import MigrationProject


class DatabaseProvider:
    name: str = "base"

    def synth(self, project: MigrationProject) -> SchemaSnapshot:
        raise NotImplementedError

    def inspect_current(self, project: MigrationProject) -> SchemaSnapshot:
        raise NotImplementedError

    def diff(self, current: SchemaSnapshot, desired: SchemaSnapshot) -> SchemaDiff:
        raise NotImplementedError

    def review(self, diff: SchemaDiff) -> str:
        raise NotImplementedError

    def current(self, project: MigrationProject) -> None:
        raise NotImplementedError

    def history(self, project: MigrationProject) -> None:
        raise NotImplementedError

    def upgrade(self, project: MigrationProject, revision: str = "head") -> None:
        raise NotImplementedError

    def downgrade(self, project: MigrationProject, revision: str) -> None:
        raise NotImplementedError

    def stamp(self, project: MigrationProject, revision: str) -> None:
        raise NotImplementedError

    def get_current_revision(self, project: MigrationProject) -> str | None:
        raise NotImplementedError

    def apply_revision(self, project: MigrationProject, revision: str | None) -> None:
        raise NotImplementedError

    def create_revision_from_snapshots(
        self,
        project: MigrationProject,
        *,
        message: str,
        current: SchemaSnapshot,
        desired: SchemaSnapshot,
        diff: SchemaDiff,
    ) -> str | None:
        raise NotImplementedError
