from db_migration_kit.providers.sqlalchemy_base import SqlAlchemyProviderBase


class SqlAlchemyPostgresProvider(SqlAlchemyProviderBase):
    name = "sqlalchemy-postgres"
