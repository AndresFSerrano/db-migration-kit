from __future__ import annotations

import dataclasses
import importlib
from typing import TYPE_CHECKING, Any

from sqlalchemy import MetaData

from db_migration_kit.schema import (
    ForeignKeySchema,
    IndexSchema,
    SchemaSnapshot,
    TableSchema,
)
from db_migration_kit.sources.base import SchemaSource
from db_migration_kit.sources.metadata import (
    _extract_column_enum_values,
    _normalized_type_name,
)

if TYPE_CHECKING:
    from db_migration_kit.project import MigrationProject


def _load_registry_module():
    try:
        registry_module = importlib.import_module("persistence_kit.repository_factory.registry.entity_registry")
        constants_module = importlib.import_module("persistence_kit.settings.constants")
        repository_module = importlib.import_module("persistence_kit.repository")
        return registry_module, constants_module, repository_module
    except ModuleNotFoundError as exc:
        raise ValueError(
            "PersistenceKitRegistrySchemaSource requiere que persistence_kit esté instalado en el entorno"
        ) from exc


class PersistenceKitRegistrySchemaSource(SchemaSource):
    name = "persistence-kit-registry"

    def __init__(self, *, registry_initializer_import_path: str) -> None:
        self._registry_initializer_import_path = registry_initializer_import_path

    def build_desired_schema(self, project: "MigrationProject") -> SchemaSnapshot:
        registry_module, constants_module, repository_module = _load_registry_module()
        initializer = self._load_initializer()
        initializer()

        entity_config: dict[str, dict[str, Any]] = getattr(registry_module, "ENTITY_CONFIG")
        database_enum = getattr(constants_module, "Database")
        build_table_from_dataclass = getattr(repository_module, "build_table_from_dataclass")
        settings = project.get_settings()

        supported_sql_backends = {"sqlalchemy-sqlite", "sqlalchemy-postgres"}
        if settings.provider_name not in supported_sql_backends:
            raise ValueError(
                f"El provider '{settings.provider_name}' no es compatible con PersistenceKitRegistrySchemaSource"
            )

        metadata = MetaData()
        tables: list[TableSchema] = []
        notes = [
            "El source de persistence_kit describe el esquema deseado desde register_entity.",
            "Las columnas y tipos se derivan de las tablas SQLAlchemy que persistence_kit construye para cada dataclass.",
        ]

        for _, config in sorted(entity_config.items()):
            backend = config.get("database")
            if backend is not None and str(getattr(backend, "value", backend)).lower() == database_enum.MONGO.value:
                continue

            table_name = str(config["collection"])
            entity_type = config.get("entity")
            if entity_type is None or not dataclasses.is_dataclass(entity_type):
                tables.append(
                    TableSchema(
                        name=table_name,
                        columns=[],
                        indexes=self._build_indexes(config),
                        foreign_keys=self._build_foreign_keys(config, entity_config, table_name),
                        column_coverage="partial",
                        source_name=self.name,
                        lazy_materialization=True,
                        notes=["Tabla sintetizada desde register_entity sin dataclass disponible para materializar tabla SQLAlchemy."],
                    )
                )
                continue

            table = build_table_from_dataclass(entity_type, table_name, metadata)
            columns = [
                self._build_column_schema(column)
                for column in table.columns
            ]
            tables.append(
                TableSchema(
                    name=table.name,
                    columns=columns,
                    indexes=self._build_indexes(config),
                    foreign_keys=self._build_foreign_keys(config, entity_config, table_name),
                    column_coverage="full",
                    source_name=self.name,
                    lazy_materialization=True,
                    notes=[
                        "Columnas y tipos derivados desde build_table_from_dataclass de persistence_kit.",
                        "Los defaults de dataclass no se promueven a server defaults en el esquema deseado.",
                        "La materialización física puede ser lazy hasta el primer uso del repositorio.",
                    ],
                )
            )

        return SchemaSnapshot(
            provider_name=settings.provider_name,
            tables=tables,
            enums=[],
            source_name=self.name,
            notes=notes,
        )

    @staticmethod
    def _build_column_schema(column: Any):
        from db_migration_kit.schema import ColumnSchema

        return ColumnSchema(
            name=column.name,
            type_name=_normalized_type_name(column.type),
            nullable=bool(column.nullable),
            default=str(column.server_default.arg) if column.server_default is not None else None,
            enum_values=_extract_column_enum_values(column.type),
        )

    @staticmethod
    def _build_indexes(config: dict[str, Any]) -> list[IndexSchema]:
        return [
            IndexSchema(
                name=f"uniq_{name}_{config['collection']}",
                columns=[str(column_name)],
                unique=True,
            )
            for name, column_name in (config.get("unique") or {}).items()
            if isinstance(column_name, str)
        ]

    @staticmethod
    def _build_foreign_keys(
        config: dict[str, Any],
        entity_config: dict[str, dict[str, Any]],
        table_name: str,
    ) -> list[ForeignKeySchema]:
        foreign_keys: list[ForeignKeySchema] = []
        for _, relation in (config.get("relations") or {}).items():
            if relation.get("through") or relation.get("target_field"):
                continue
            local_field = str(relation["local_field"])
            target_table = str(entity_config[relation["target"]]["collection"])
            target_column = str(relation.get("by", "id"))
            foreign_keys.append(
                ForeignKeySchema(
                    name=f"fk_{table_name}_{local_field}",
                    constrained_columns=[local_field],
                    referred_table=target_table,
                    referred_columns=[target_column],
                )
            )
        return foreign_keys

    def _load_initializer(self):
        module_path, _, attribute = self._registry_initializer_import_path.partition(":")
        if not module_path or not attribute:
            raise ValueError(
                "registry_initializer_import_path debe tener formato 'modulo:ruta_atributo'"
            )
        value: Any = importlib.import_module(module_path)
        for part in attribute.split("."):
            value = getattr(value, part)
        if not callable(value):
            raise ValueError("El inicializador del registry debe ser callable")
        return value
