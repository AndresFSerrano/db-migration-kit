from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import MetaData
from sqlalchemy.sql.schema import ForeignKeyConstraint
from sqlalchemy.sql.sqltypes import Enum as SqlEnum

from db_migration_kit.schema import (
    ColumnSchema,
    EnumSchema,
    ForeignKeySchema,
    IndexSchema,
    SchemaSnapshot,
    TableSchema,
)
from db_migration_kit.sources.base import SchemaSource

if TYPE_CHECKING:
    from db_migration_kit.project import MigrationProject


def _normalized_type_name(raw: object) -> str:
    return str(raw).lower().strip()


def _extract_column_enum_values(raw_type: object) -> list[str]:
    if isinstance(raw_type, SqlEnum):
        return [str(value) for value in raw_type.enums]
    return []


class SqlAlchemyMetadataSchemaSource(SchemaSource):
    name = "sqlalchemy-metadata"

    def build_desired_schema(self, project: "MigrationProject") -> SchemaSnapshot:
        metadata = project.get_metadata()
        if metadata is None:
            raise ValueError("El source sqlalchemy-metadata requiere metadata")
        if not isinstance(metadata, MetaData):
            raise ValueError("get_metadata() debe retornar sqlalchemy.MetaData")

        tables: list[TableSchema] = []
        enums: dict[str, EnumSchema] = {}
        for table in metadata.sorted_tables:
            columns = [
                ColumnSchema(
                    name=column.name,
                    type_name=_normalized_type_name(column.type),
                    nullable=bool(column.nullable),
                    default=str(column.server_default.arg) if column.server_default is not None else None,
                    enum_values=_extract_column_enum_values(column.type),
                )
                for column in table.columns
            ]
            indexes = [
                IndexSchema(
                    name=index.name or f"idx_{table.name}_{'_'.join(column.name for column in index.columns)}",
                    columns=[column.name for column in index.columns],
                    unique=bool(index.unique),
                )
                for index in table.indexes
            ]
            foreign_keys = []
            for constraint in table.constraints:
                if not isinstance(constraint, ForeignKeyConstraint):
                    continue
                foreign_keys.append(
                    ForeignKeySchema(
                        name=constraint.name or f"fk_{table.name}_{'_'.join(column.name for column in constraint.columns)}",
                        constrained_columns=[column.name for column in constraint.columns],
                        referred_table=next(iter(constraint.elements)).column.table.name,
                        referred_columns=[element.column.name for element in constraint.elements],
                    )
                )
            for column in table.columns:
                if isinstance(column.type, SqlEnum):
                    enum_name = column.type.name or f"enum_{table.name}_{column.name}"
                    enums[enum_name] = EnumSchema(
                        name=enum_name,
                        values=[str(value) for value in column.type.enums],
                    )
            tables.append(TableSchema(name=table.name, columns=columns, indexes=indexes, foreign_keys=foreign_keys))

        return SchemaSnapshot(
            provider_name=project.get_settings().provider_name,
            tables=tables,
            enums=list(enums.values()),
            source_name=self.name,
        )
