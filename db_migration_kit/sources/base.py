from __future__ import annotations

from typing import TYPE_CHECKING

from db_migration_kit.schema import SchemaSnapshot

if TYPE_CHECKING:
    from db_migration_kit.project import MigrationProject


class SchemaSource:
    name: str = "base"

    def build_desired_schema(self, project: "MigrationProject") -> SchemaSnapshot:
        raise NotImplementedError
