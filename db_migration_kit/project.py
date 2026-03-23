from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from db_migration_kit.config import MigrationProjectSettings
from db_migration_kit.providers.registry import get_provider
from db_migration_kit.sources.metadata import SqlAlchemyMetadataSchemaSource

if TYPE_CHECKING:
    from db_migration_kit.providers.base import DatabaseProvider
    from db_migration_kit.sources.base import SchemaSource


class MigrationProject:
    def get_settings(self) -> MigrationProjectSettings:
        raise NotImplementedError

    def get_metadata(self) -> Any | None:
        metadata_import_path = self.get_settings().metadata_import_path
        if not metadata_import_path:
            return None
        module_path, _, attribute = metadata_import_path.partition(":")
        if not module_path or not attribute:
            raise ValueError("metadata_import_path debe tener formato 'modulo:ruta_atributo'")
        value: Any = importlib.import_module(module_path)
        for part in attribute.split("."):
            value = getattr(value, part)
        return value

    def get_provider(self) -> DatabaseProvider:
        return get_provider(self.get_settings().provider_name)

    def get_schema_source(self) -> "SchemaSource":
        return SqlAlchemyMetadataSchemaSource()

    def pre_upgrade(self) -> None:
        return None

    def post_upgrade(self) -> None:
        return None
