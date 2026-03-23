from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from pathlib import Path
from sqlalchemy import MetaData, create_engine, inspect
from alembic.runtime.migration import MigrationContext
from sqlalchemy.sql.schema import ForeignKeyConstraint
from sqlalchemy.sql.sqltypes import Enum as SqlEnum

from db_migration_kit.providers.base import DatabaseProvider
from db_migration_kit.schema import (
    ColumnSchema,
    EnumSchema,
    ForeignKeySchema,
    IndexSchema,
    SchemaChange,
    SchemaDiff,
    SchemaSnapshot,
    TableSchema,
)

if TYPE_CHECKING:
    from db_migration_kit.project import MigrationProject


def _normalized_type_name(raw: object) -> str:
    return str(raw).lower().strip()


def _column_signature(column: ColumnSchema) -> tuple[str, bool, str | None, tuple[str, ...]]:
    return (column.type_name, column.nullable, column.default, tuple(column.enum_values))


def _fk_signature(foreign_key: ForeignKeySchema) -> tuple[tuple[str, ...], str, tuple[str, ...]]:
    return (
        tuple(foreign_key.constrained_columns),
        foreign_key.referred_table,
        tuple(foreign_key.referred_columns),
    )


def _extract_column_enum_values(raw_type: object) -> list[str]:
    if isinstance(raw_type, SqlEnum):
        return [str(value) for value in raw_type.enums]
    return []


class SqlAlchemyProviderBase(DatabaseProvider):
    name = "sqlalchemy-base"

    def _build_alembic_config(self, project: "MigrationProject") -> Config:
        settings = project.get_settings()
        config = Config(str(settings.normalized_alembic_ini_path()))
        config.set_main_option("script_location", str(settings.normalized_migrations_dir()))
        config.set_main_option("sqlalchemy.url", settings.sync_database_url or settings.database_url)
        config.set_main_option("version_table", settings.version_table)
        return config

    def synth(self, project: "MigrationProject") -> SchemaSnapshot:
        return project.get_schema_source().build_desired_schema(project)

    def inspect_current(self, project: "MigrationProject") -> SchemaSnapshot:
        settings = project.get_settings()
        database_url = settings.sync_database_url or settings.database_url
        engine = create_engine(database_url)
        try:
            inspector = inspect(engine)
            tables: list[TableSchema] = []
            enums: list[EnumSchema] = []
            if self.supports_native_enums() and hasattr(inspector, "get_enums"):
                for enum_item in inspector.get_enums():
                    enums.append(
                        EnumSchema(
                            name=str(enum_item.get("name") or ""),
                            values=[str(value) for value in enum_item.get("labels") or []],
                        )
                    )
            version_table = settings.version_table
            for table_name in inspector.get_table_names():
                if table_name == version_table:
                    continue
                columns = []
                for column in inspector.get_columns(table_name):
                    columns.append(
                        ColumnSchema(
                            name=str(column["name"]),
                            type_name=_normalized_type_name(column["type"]),
                            nullable=bool(column.get("nullable", True)),
                            default=str(column.get("default")) if column.get("default") is not None else None,
                            enum_values=_extract_column_enum_values(column["type"]),
                        )
                    )
                indexes = [
                    IndexSchema(
                        name=str(index.get("name") or f"idx_{table_name}_{'_'.join(index.get('column_names') or [])}"),
                        columns=[str(name) for name in index.get("column_names") or []],
                        unique=bool(index.get("unique", False)),
                    )
                    for index in inspector.get_indexes(table_name)
                ]
                foreign_keys = [
                    ForeignKeySchema(
                        name=str(foreign_key.get("name") or f"fk_{table_name}_{'_'.join(foreign_key.get('constrained_columns') or [])}"),
                        constrained_columns=[str(name) for name in foreign_key.get("constrained_columns") or []],
                        referred_table=str(foreign_key.get("referred_table") or ""),
                        referred_columns=[str(name) for name in foreign_key.get("referred_columns") or []],
                    )
                    for foreign_key in inspector.get_foreign_keys(table_name)
                ]
                tables.append(TableSchema(name=table_name, columns=columns, indexes=indexes, foreign_keys=foreign_keys))
            return SchemaSnapshot(provider_name=self.name, tables=tables, enums=enums)
        finally:
            engine.dispose()

    def supports_native_enums(self) -> bool:
        return True

    def diff(self, current: SchemaSnapshot, desired: SchemaSnapshot) -> SchemaDiff:
        diff = SchemaDiff(provider_name=self.name)
        current_tables = current.by_table_name()
        desired_tables = desired.by_table_name()
        current_enums = current.by_enum_name()
        desired_enums = desired.by_enum_name()

        self._append_enum_changes(diff, current_enums, desired_enums)

        for table_name, desired_table in sorted(desired_tables.items()):
            current_table = current_tables.get(table_name)
            if current_table is None:
                if desired_table.lazy_materialization:
                    diff.changes.append(
                        SchemaChange(
                            change_type="pendiente",
                            object_type="tabla-lazy",
                            object_name=table_name,
                            details=(
                                f"La tabla '{table_name}' todavía no existe físicamente. "
                                "Esto puede ser esperable si persistence_kit la materializa de forma lazy "
                                "hasta el primer uso del repositorio."
                            ),
                        )
                    )
                    continue
                diff.changes.append(
                    SchemaChange(
                        change_type="agregar",
                        object_type="tabla",
                        object_name=table_name,
                        details=f"Se agregará la tabla '{table_name}' con {len(desired_table.columns)} columnas.",
                    )
                )
                continue

            current_columns = current_table.by_column_name()
            desired_columns = desired_table.by_column_name()
            self._append_possible_column_renames(diff, table_name, current_columns, desired_columns)

            for column_name, desired_column in sorted(desired_columns.items()):
                current_column = current_columns.get(column_name)
                if current_column is None:
                    diff.changes.append(
                        SchemaChange(
                            change_type="agregar",
                            object_type="columna",
                            object_name=f"{table_name}.{column_name}",
                            details=(
                                f"Se agregará la columna '{column_name}' en '{table_name}' "
                                f"con tipo '{desired_column.type_name}' y nullable={desired_column.nullable}."
                            ),
                        )
                    )
                    continue
                if current_column.type_name != desired_column.type_name:
                    diff.changes.append(
                        SchemaChange(
                            change_type="modificar",
                            object_type="columna",
                            object_name=f"{table_name}.{column_name}",
                            details=(
                                f"La columna '{column_name}' en '{table_name}' cambiará de tipo "
                                f"'{current_column.type_name}' a '{desired_column.type_name}'."
                            ),
                        )
                    )
                if current_column.nullable != desired_column.nullable:
                    diff.changes.append(
                        SchemaChange(
                            change_type="modificar",
                            object_type="columna",
                            object_name=f"{table_name}.{column_name}",
                            details=(
                                f"La columna '{column_name}' en '{table_name}' cambiará nullable "
                                f"de {current_column.nullable} a {desired_column.nullable}."
                            ),
                        )
                    )
                if current_column.default != desired_column.default:
                    diff.changes.append(
                        SchemaChange(
                            change_type="modificar",
                            object_type="columna",
                            object_name=f"{table_name}.{column_name}",
                            details=(
                                f"La columna '{column_name}' en '{table_name}' cambiará default "
                                f"de {current_column.default!r} a {desired_column.default!r}."
                            ),
                        )
                    )
                if current_column.enum_values != desired_column.enum_values:
                    diff.changes.append(
                        SchemaChange(
                            change_type="modificar",
                            object_type="enum-columna",
                            object_name=f"{table_name}.{column_name}",
                            details=(
                                f"La columna '{column_name}' en '{table_name}' cambiará sus valores enum "
                                f"de {current_column.enum_values} a {desired_column.enum_values}."
                            ),
                        )
                    )

            for column_name in sorted(set(current_columns) - set(desired_columns)):
                diff.changes.append(
                    SchemaChange(
                        change_type="eliminar",
                        object_type="columna",
                        object_name=f"{table_name}.{column_name}",
                        details=f"La columna '{column_name}' existe hoy en '{table_name}' pero no en el esquema deseado.",
                    )
                )

            self._append_index_changes(diff, table_name, current_table.by_index_name(), desired_table.by_index_name())
            self._append_fk_changes(diff, table_name, current_table.by_fk_name(), desired_table.by_fk_name())

        for table_name in sorted(set(current_tables) - set(desired_tables)):
            diff.changes.append(
                SchemaChange(
                    change_type="eliminar",
                    object_type="tabla",
                    object_name=table_name,
                    details=f"La tabla '{table_name}' existe hoy pero no aparece en el esquema deseado.",
                )
            )

        return diff

    def _append_enum_changes(
        self,
        diff: SchemaDiff,
        current_enums: dict[str, EnumSchema],
        desired_enums: dict[str, EnumSchema],
    ) -> None:
        for enum_name, desired_enum in sorted(desired_enums.items()):
            current_enum = current_enums.get(enum_name)
            if current_enum is None:
                diff.changes.append(
                    SchemaChange(
                        change_type="agregar",
                        object_type="enum",
                        object_name=enum_name,
                        details=f"Se agregará el enum '{enum_name}' con valores {desired_enum.values}.",
                    )
                )
                continue
            if current_enum.values != desired_enum.values:
                diff.changes.append(
                    SchemaChange(
                        change_type="modificar",
                        object_type="enum",
                        object_name=enum_name,
                        details=f"El enum '{enum_name}' cambiará de {current_enum.values} a {desired_enum.values}.",
                    )
                )
        for enum_name in sorted(set(current_enums) - set(desired_enums)):
            diff.changes.append(
                SchemaChange(
                    change_type="eliminar",
                    object_type="enum",
                    object_name=enum_name,
                    details=f"El enum '{enum_name}' existe hoy pero no aparece en el esquema deseado.",
                )
            )

    def _append_possible_column_renames(
        self,
        diff: SchemaDiff,
        table_name: str,
        current_columns: dict[str, ColumnSchema],
        desired_columns: dict[str, ColumnSchema],
    ) -> None:
        removed = {name: current_columns[name] for name in set(current_columns) - set(desired_columns)}
        added = {name: desired_columns[name] for name in set(desired_columns) - set(current_columns)}
        for removed_name, removed_column in sorted(removed.items()):
            for added_name, added_column in sorted(added.items()):
                if _column_signature(removed_column) == _column_signature(added_column):
                    diff.changes.append(
                        SchemaChange(
                            change_type="riesgo",
                            object_type="renombre-posible",
                            object_name=f"{table_name}.{removed_name}->{added_name}",
                            details=(
                                f"Se detectó un posible renombre de columna en '{table_name}': "
                                f"'{removed_name}' podría haber pasado a '{added_name}'. "
                                "Revise si debe generarse una migración de rename en lugar de drop + add."
                            ),
                        )
                    )

    def _append_index_changes(
        self,
        diff: SchemaDiff,
        table_name: str,
        current_indexes: dict[str, IndexSchema],
        desired_indexes: dict[str, IndexSchema],
    ) -> None:
        current_indexes = self._filter_auxiliary_fk_indexes(table_name, current_indexes)
        desired_indexes = self._filter_auxiliary_fk_indexes(table_name, desired_indexes)
        for index_name, desired_index in sorted(desired_indexes.items()):
            current_index = current_indexes.get(index_name)
            if current_index is None:
                diff.changes.append(
                    SchemaChange(
                        change_type="agregar",
                        object_type="indice",
                        object_name=f"{table_name}.{index_name}",
                        details=(
                            f"Se agregará el índice '{index_name}' en '{table_name}' "
                            f"sobre columnas {desired_index.columns} con unique={desired_index.unique}."
                        ),
                    )
                )
                continue
            if current_index.columns != desired_index.columns or current_index.unique != desired_index.unique:
                diff.changes.append(
                    SchemaChange(
                        change_type="modificar",
                        object_type="indice",
                        object_name=f"{table_name}.{index_name}",
                        details=(
                            f"El índice '{index_name}' en '{table_name}' cambiará "
                            f"de columnas {current_index.columns}/unique={current_index.unique} "
                            f"a {desired_index.columns}/unique={desired_index.unique}."
                        ),
                    )
                )
        for index_name in sorted(set(current_indexes) - set(desired_indexes)):
            diff.changes.append(
                SchemaChange(
                    change_type="eliminar",
                    object_type="indice",
                    object_name=f"{table_name}.{index_name}",
                    details=f"El índice '{index_name}' existe hoy en '{table_name}' pero no en el esquema deseado.",
                )
            )

    def _append_fk_changes(
        self,
        diff: SchemaDiff,
        table_name: str,
        current_foreign_keys: dict[str, ForeignKeySchema],
        desired_foreign_keys: dict[str, ForeignKeySchema],
    ) -> None:
        current_by_signature = {
            _fk_signature(foreign_key): foreign_key
            for foreign_key in current_foreign_keys.values()
        }
        desired_by_signature = {
            _fk_signature(foreign_key): foreign_key
            for foreign_key in desired_foreign_keys.values()
        }

        for signature, desired_foreign_key in sorted(desired_by_signature.items()):
            current_foreign_key = current_by_signature.get(signature)
            if current_foreign_key is None:
                diff.changes.append(
                    SchemaChange(
                        change_type="agregar",
                        object_type="foreign-key",
                        object_name=f"{table_name}.{desired_foreign_key.name}",
                        details=(
                            f"Se agregará la FK '{desired_foreign_key.name}' en '{table_name}' "
                            f"desde {desired_foreign_key.constrained_columns} hacia "
                            f"{desired_foreign_key.referred_table}({desired_foreign_key.referred_columns})."
                        ),
                    )
                )
                continue
            if _fk_signature(current_foreign_key) != signature:
                diff.changes.append(
                    SchemaChange(
                        change_type="modificar",
                        object_type="foreign-key",
                        object_name=f"{table_name}.{desired_foreign_key.name}",
                        details=(
                            f"La FK '{desired_foreign_key.name}' en '{table_name}' cambiará "
                            f"de {_fk_signature(current_foreign_key)} a {signature}."
                        ),
                    )
                )

        for signature, current_foreign_key in sorted(current_by_signature.items()):
            if signature in desired_by_signature:
                continue
            diff.changes.append(
                SchemaChange(
                    change_type="eliminar",
                    object_type="foreign-key",
                    object_name=f"{table_name}.{current_foreign_key.name}",
                    details=f"La FK '{current_foreign_key.name}' existe hoy en '{table_name}' pero no en el esquema deseado.",
                )
            )

    @staticmethod
    def _filter_auxiliary_fk_indexes(
        table_name: str,
        indexes: dict[str, IndexSchema],
    ) -> dict[str, IndexSchema]:
        filtered: dict[str, IndexSchema] = {}
        prefix = f"idx_{table_name}_"
        for index_name, index in indexes.items():
            if index_name.startswith(prefix) and not index.unique:
                continue
            filtered[index_name] = index
        return filtered

    def review(self, diff: SchemaDiff) -> str:
        if not diff.changes:
            return "No hay cambios detectados entre el esquema actual y el esquema deseado."
        lines = [f"Revisión del cambio de esquema para provider '{self.name}':"]
        for index, change in enumerate(diff.changes, start=1):
            lines.append(f"{index}. [{change.change_type}] {change.object_type} {change.object_name}")
            lines.append(f"   {change.details}")
        lines.append("")
        lines.append("Nota: los posibles renombres y las migraciones de datos deben revisarse manualmente antes de aplicar cambios.")
        return "\n".join(lines)

    def current(self, project: "MigrationProject") -> None:
        command.current(self._build_alembic_config(project), verbose=True)

    def history(self, project: "MigrationProject") -> None:
        command.history(self._build_alembic_config(project), verbose=True)

    def upgrade(self, project: "MigrationProject", revision: str = "head") -> None:
        project.pre_upgrade()
        command.upgrade(self._build_alembic_config(project), revision)
        project.post_upgrade()

    def downgrade(self, project: "MigrationProject", revision: str) -> None:
        command.downgrade(self._build_alembic_config(project), revision)

    def stamp(self, project: "MigrationProject", revision: str) -> None:
        command.stamp(self._build_alembic_config(project), revision)

    def create_revision_from_snapshots(
        self,
        project: "MigrationProject",
        *,
        message: str,
        current: SchemaSnapshot,
        desired: SchemaSnapshot,
        diff: SchemaDiff,
    ) -> str | None:
        executable_changes = [
            change
            for change in diff.changes
            if change.change_type not in {"pendiente", "riesgo"}
        ]
        if not executable_changes:
            return self.get_current_revision(project)

        config = self._build_alembic_config(project)
        script = command.revision(config, message=message, autogenerate=False)
        script_path = Path(str(script.path))
        operations = self._build_revision_operations(current=current, desired=desired)
        upgrade_lines = operations["upgrade"]
        downgrade_lines = operations["downgrade"]
        if not upgrade_lines:
            script_path.unlink(missing_ok=True)
            return self.get_current_revision(project)
        script_path.write_text(
            self._render_revision_file(
                revision=script.revision,
                down_revision=script.down_revision,
                message=message,
                upgrade_lines=upgrade_lines,
                downgrade_lines=downgrade_lines,
            ),
            encoding="utf-8",
        )
        return str(script.revision)

    def get_current_revision(self, project: "MigrationProject") -> str | None:
        settings = project.get_settings()
        database_url = settings.sync_database_url or settings.database_url
        engine = create_engine(database_url)
        try:
            with engine.connect() as connection:
                context = MigrationContext.configure(connection)
                return context.get_current_revision()
        finally:
            engine.dispose()

    def apply_revision(self, project: "MigrationProject", revision: str | None) -> None:
        target_revision = None if revision in (None, "", "base") else revision
        current_revision = self.get_current_revision(project)
        if current_revision == target_revision:
            return

        config = self._build_alembic_config(project)
        if target_revision is None:
            command.downgrade(config, "base")
            return
        if current_revision is None:
            project.pre_upgrade()
            command.upgrade(config, target_revision)
            project.post_upgrade()
            return

        script = ScriptDirectory.from_config(config)
        if self._is_ancestor_revision(script, current_revision, target_revision):
            project.pre_upgrade()
            command.upgrade(config, target_revision)
            project.post_upgrade()
            return
        if self._is_ancestor_revision(script, target_revision, current_revision):
            command.downgrade(config, target_revision)
            return
        raise ValueError(
            f"No se pudo determinar una ruta lineal entre la revision actual '{current_revision}' "
            f"y la revision objetivo '{target_revision}'."
        )

    def _build_revision_operations(
        self,
        *,
        current: SchemaSnapshot,
        desired: SchemaSnapshot,
    ) -> dict[str, list[str]]:
        current_tables = current.by_table_name()
        desired_tables = desired.by_table_name()
        upgrade_lines: list[str] = []
        downgrade_lines: list[str] = []
        needs_pgcrypto = False

        for table_name, desired_table in sorted(desired_tables.items()):
            current_table = current_tables.get(table_name)
            if current_table is None:
                if desired_table.lazy_materialization:
                    continue
                upgrade_lines.extend(self._render_create_table(table_name, desired_table))
                downgrade_lines.insert(0, f'op.drop_table("{table_name}")')
                continue

            current_columns = current_table.by_column_name()
            desired_columns = desired_table.by_column_name()
            for column_name, desired_column in sorted(desired_columns.items()):
                if column_name not in current_columns:
                    if not desired_column.nullable and desired_column.default is None:
                        is_unique = self._column_is_unique(column_name, desired_table.indexes)
                        safe_default, use_pgcrypto = self._safe_default_for_column(desired_column, is_unique)
                        needs_pgcrypto = needs_pgcrypto or use_pgcrypto
                        upgrade_lines.append(
                            f'op.add_column("{table_name}", {self._render_column_as_nullable(desired_column)})'
                        )
                        upgrade_lines.append(
                            f'op.execute("UPDATE {table_name} SET {column_name} = {safe_default} WHERE {column_name} IS NULL")'
                        )
                        upgrade_lines.append(
                            f'op.alter_column("{table_name}", "{column_name}", '
                            f'existing_type={self._render_type(desired_column.type_name)}, nullable=False)'
                        )
                    else:
                        upgrade_lines.append(
                            f'op.add_column("{table_name}", {self._render_column(desired_column)})'
                        )
                    downgrade_lines.insert(
                        0,
                        f'op.drop_column("{table_name}", "{column_name}")',
                    )
                    continue
                current_column = current_columns[column_name]
                if current_column.nullable != desired_column.nullable:
                    if not desired_column.nullable:
                        is_unique = self._column_is_unique(column_name, desired_table.indexes)
                        safe_default, use_pgcrypto = self._safe_default_for_column(desired_column, is_unique)
                        needs_pgcrypto = needs_pgcrypto or use_pgcrypto
                        upgrade_lines.append(
                            f'op.execute("UPDATE {table_name} SET {column_name} = {safe_default} WHERE {column_name} IS NULL")'
                        )
                    upgrade_lines.append(
                        f'op.alter_column("{table_name}", "{column_name}", existing_type={self._render_type(current_column.type_name)}, nullable={desired_column.nullable})'
                    )
                    downgrade_lines.insert(
                        0,
                        f'op.alter_column("{table_name}", "{column_name}", existing_type={self._render_type(desired_column.type_name)}, nullable={current_column.nullable})',
                    )

            # Index changes — always AFTER column ops to avoid unique violations on backfilled data
            current_indexes = self._filter_auxiliary_fk_indexes(table_name, current_table.by_index_name())
            desired_indexes = self._filter_auxiliary_fk_indexes(table_name, desired_table.by_index_name())
            for index_name, desired_index in sorted(desired_indexes.items()):
                if index_name not in current_indexes:
                    upgrade_lines.append(
                        f'op.create_index("{index_name}", "{table_name}", {desired_index.columns!r}, unique={desired_index.unique})'
                    )
                    downgrade_lines.insert(0, f'op.drop_index("{index_name}", table_name="{table_name}")')
            for index_name in sorted(set(current_indexes) - set(desired_indexes)):
                current_index = current_indexes[index_name]
                upgrade_lines.append(f'op.drop_index("{index_name}", table_name="{table_name}")')
                downgrade_lines.insert(
                    0,
                    f'op.create_index("{index_name}", "{table_name}", {current_index.columns!r}, unique={current_index.unique})',
                )

        if needs_pgcrypto:
            upgrade_lines.insert(0, 'op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")')

        return {"upgrade": upgrade_lines, "downgrade": downgrade_lines}

    def _render_create_table(self, table_name: str, table: TableSchema) -> list[str]:
        lines: list[str] = []
        column_defs = [self._render_column(column) for column in table.columns]
        pk_columns = [column.name for column in table.columns if column.name == "id"]
        if pk_columns:
            column_defs.append(
                "sa.PrimaryKeyConstraint(" + ", ".join(f'"{name}"' for name in pk_columns) + ")"
            )
        lines.append(f'op.create_table("{table_name}",')
        for column_def in column_defs:
            lines.append(f"    {column_def},")
        lines.append(")")
        for index in table.indexes:
            lines.append(
                f'op.create_index("{index.name}", "{table_name}", {index.columns!r}, unique={index.unique})'
            )
        for foreign_key in table.foreign_keys:
            lines.append(
                f'op.create_foreign_key("{foreign_key.name}", "{table_name}", "{foreign_key.referred_table}", {foreign_key.constrained_columns!r}, {foreign_key.referred_columns!r})'
            )
        return lines

    def _render_column(self, column: ColumnSchema) -> str:
        return (
            f'sa.Column("{column.name}", {self._render_type(column.type_name)}, '
            f'nullable={column.nullable})'
        )

    def _render_column_as_nullable(self, column: ColumnSchema) -> str:
        return (
            f'sa.Column("{column.name}", {self._render_type(column.type_name)}, '
            f'nullable=True)'
        )

    @staticmethod
    def _column_is_unique(column_name: str, indexes: list[IndexSchema]) -> bool:
        return any(index.unique and index.columns == [column_name] for index in indexes)

    @staticmethod
    def _safe_default_for_column(column: ColumnSchema, unique: bool) -> tuple[str, bool]:
        """Returns (sql_expression, needs_pgcrypto)."""
        normalized = column.type_name.lower()
        if normalized == "uuid":
            return "gen_random_uuid()", True
        if normalized in {"varchar", "string"}:
            if unique:
                return "gen_random_uuid()::text", True
            return "''", False
        if normalized == "integer":
            return "0", False
        if normalized == "boolean":
            return "false", False
        if normalized == "float":
            return "0.0", False
        if normalized in {"datetime", "timestamp without time zone"}:
            return "now()", False
        if normalized == "date":
            return "current_date", False
        return "null", False

    def _render_type(self, type_name: str) -> str:
        normalized = type_name.lower()
        if normalized in {"varchar", "string"}:
            return "sa.String()"
        if normalized == "uuid":
            return "postgresql.UUID(as_uuid=True)"
        if normalized == "boolean":
            return "sa.Boolean()"
        if normalized == "integer":
            return "sa.Integer()"
        if normalized == "float":
            return "sa.Float()"
        if normalized in {"datetime", "timestamp without time zone"}:
            return "sa.DateTime()"
        if normalized == "date":
            return "sa.Date()"
        raise ValueError(f"Tipo de columna no soportado para generar revision automaticamente: {type_name}")

    def _render_revision_file(
        self,
        *,
        revision: str,
        down_revision: str | tuple[str, ...] | None,
        message: str,
        upgrade_lines: list[str],
        downgrade_lines: list[str],
    ) -> str:
        def _repr_down_revision(value: str | tuple[str, ...] | None) -> str:
            if value is None:
                return "None"
            if isinstance(value, tuple):
                return repr(tuple(value))
            return repr(value)

        upgrade_body = "\n".join(f"    {line}" for line in upgrade_lines) or "    pass"
        downgrade_body = "\n".join(f"    {line}" for line in downgrade_lines) or "    pass"
        return f'''"""{message}"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = {revision!r}
down_revision = {_repr_down_revision(down_revision)}
branch_labels = None
depends_on = None


def upgrade() -> None:
{upgrade_body}


def downgrade() -> None:
{downgrade_body}
'''

    def _is_ancestor_revision(
        self,
        script: ScriptDirectory,
        ancestor_revision: str,
        descendant_revision: str,
    ) -> bool:
        if ancestor_revision == descendant_revision:
            return True
        target = script.get_revision(descendant_revision)
        if target is None:
            raise ValueError(f"La revision '{descendant_revision}' no existe en Alembic.")
        pending = [target]
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current.revision in visited:
                continue
            visited.add(current.revision)
            down_revision = current.down_revision
            if down_revision is None:
                continue
            if isinstance(down_revision, tuple):
                for revision_id in down_revision:
                    if revision_id == ancestor_revision:
                        return True
                    parent = script.get_revision(revision_id)
                    if parent is not None:
                        pending.append(parent)
                continue
            if down_revision == ancestor_revision:
                return True
            parent = script.get_revision(down_revision)
            if parent is not None:
                pending.append(parent)
        return False
