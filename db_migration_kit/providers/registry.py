from __future__ import annotations

from db_migration_kit.providers.base import DatabaseProvider
from db_migration_kit.providers.sqlalchemy_postgres import SqlAlchemyPostgresProvider
from db_migration_kit.providers.sqlalchemy_sqlite import SqlAlchemySqliteProvider


_PROVIDERS: dict[str, DatabaseProvider] = {
    "sqlalchemy-sqlite": SqlAlchemySqliteProvider(),
    "sqlalchemy-postgres": SqlAlchemyPostgresProvider(),
}


def get_provider(name: str) -> DatabaseProvider:
    provider = _PROVIDERS.get(name)
    if provider is None:
        raise ValueError(f"Provider desconocido: {name}")
    return provider
