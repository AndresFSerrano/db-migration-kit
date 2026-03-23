from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ColumnSchema:
    name: str
    type_name: str
    nullable: bool
    default: str | None = None
    enum_values: list[str] = field(default_factory=list)


@dataclass(slots=True)
class IndexSchema:
    name: str
    columns: list[str] = field(default_factory=list)
    unique: bool = False


@dataclass(slots=True)
class ForeignKeySchema:
    name: str
    constrained_columns: list[str] = field(default_factory=list)
    referred_table: str = ""
    referred_columns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EnumSchema:
    name: str
    values: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TableSchema:
    name: str
    columns: list[ColumnSchema] = field(default_factory=list)
    indexes: list[IndexSchema] = field(default_factory=list)
    foreign_keys: list[ForeignKeySchema] = field(default_factory=list)
    column_coverage: str = "full"
    source_name: str | None = None
    lazy_materialization: bool = False
    notes: list[str] = field(default_factory=list)

    def by_column_name(self) -> dict[str, ColumnSchema]:
        return {column.name: column for column in self.columns}

    def by_index_name(self) -> dict[str, IndexSchema]:
        return {index.name: index for index in self.indexes}

    def by_fk_name(self) -> dict[str, ForeignKeySchema]:
        return {foreign_key.name: foreign_key for foreign_key in self.foreign_keys}


@dataclass(slots=True)
class SchemaSnapshot:
    provider_name: str
    tables: list[TableSchema] = field(default_factory=list)
    enums: list[EnumSchema] = field(default_factory=list)
    source_name: str | None = None
    notes: list[str] = field(default_factory=list)

    def by_table_name(self) -> dict[str, TableSchema]:
        return {table.name: table for table in self.tables}

    def by_enum_name(self) -> dict[str, EnumSchema]:
        return {enum_schema.name: enum_schema for enum_schema in self.enums}


@dataclass(slots=True)
class SchemaChange:
    change_type: str
    object_type: str
    object_name: str
    details: str


@dataclass(slots=True)
class SchemaDiff:
    provider_name: str
    changes: list[SchemaChange] = field(default_factory=list)

    def has_changes(self) -> bool:
        return bool(self.changes)
