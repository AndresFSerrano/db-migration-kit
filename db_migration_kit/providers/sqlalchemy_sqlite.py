from db_migration_kit.providers.sqlalchemy_base import SqlAlchemyProviderBase


class SqlAlchemySqliteProvider(SqlAlchemyProviderBase):
    name = "sqlalchemy-sqlite"

    def supports_native_enums(self) -> bool:
        return False
