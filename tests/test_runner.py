import dataclasses
from pathlib import Path

from sqlalchemy import Column, ForeignKey, Index, Integer, MetaData, String, Table
from sqlalchemy.sql.sqltypes import Enum as SqlEnum

from db_migration_kit import MigrationProject, MigrationProjectSettings, MigrationRunner
from db_migration_kit.providers.base import DatabaseProvider
from db_migration_kit.providers.sqlalchemy_postgres import SqlAlchemyPostgresProvider
from db_migration_kit.providers.sqlalchemy_sqlite import SqlAlchemySqliteProvider
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
from db_migration_kit.sources.persistence_kit_registry import PersistenceKitRegistrySchemaSource
from db_migration_kit.sources.base import SchemaSource


class DummyProject(MigrationProject):
    def get_settings(self) -> MigrationProjectSettings:
        return MigrationProjectSettings(
            project_name="dummy",
            migrations_dir=Path("."),
            database_url="sqlite:///tmp.db",
        )

    def get_metadata(self):
        metadata = MetaData()
        Table(
            "usuarios",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("nombre", String(100), nullable=False),
            Column("estado", SqlEnum("activo", "inactivo", name="estado_usuario"), nullable=False),
        )
        Table(
            "perfiles",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("usuario_id", Integer, ForeignKey("usuarios.id"), nullable=False),
        )
        Index("idx_usuarios_nombre", metadata.tables["usuarios"].c.nombre)
        return metadata

    def get_provider(self):
        return SqlAlchemySqliteProvider()


def test_runner_doctor_returns_expected_fields() -> None:
    runner = MigrationRunner(DummyProject())
    info = runner.doctor()
    assert info["project_name"] == "dummy"
    assert info["provider_name"] == "sqlalchemy-sqlite"


def test_provider_diff_reports_type_and_column_changes() -> None:
    provider = SqlAlchemyPostgresProvider()
    current = SchemaSnapshot(
        provider_name=provider.name,
        tables=[
            TableSchema(
                name="usuarios",
                columns=[
                    ColumnSchema(name="id", type_name="integer", nullable=False),
                    ColumnSchema(name="nombre", type_name="varchar(50)", nullable=True),
                    ColumnSchema(name="legacy", type_name="varchar(20)", nullable=True),
                    ColumnSchema(name="estado", type_name="varchar(8)", nullable=False, enum_values=["activo"]),
                ],
                indexes=[IndexSchema(name="idx_usuarios_legacy", columns=["legacy"], unique=False)],
                foreign_keys=[],
            )
        ],
        enums=[EnumSchema(name="estado_usuario", values=["activo"])],
    )
    desired = SchemaSnapshot(
        provider_name=provider.name,
        tables=[
            TableSchema(
                name="usuarios",
                columns=[
                    ColumnSchema(name="id", type_name="integer", nullable=False),
                    ColumnSchema(name="nombre", type_name="varchar(100)", nullable=False),
                    ColumnSchema(name="email", type_name="varchar(120)", nullable=True),
                    ColumnSchema(name="estado", type_name="varchar(8)", nullable=False, enum_values=["activo", "inactivo"]),
                ],
                indexes=[IndexSchema(name="idx_usuarios_nombre", columns=["nombre"], unique=False)],
                foreign_keys=[],
            ),
            TableSchema(
                name="perfiles",
                columns=[
                    ColumnSchema(name="id", type_name="integer", nullable=False),
                    ColumnSchema(name="usuario_id", type_name="integer", nullable=False),
                ],
                indexes=[],
                foreign_keys=[
                    ForeignKeySchema(
                        name="fk_perfiles_usuario_id",
                        constrained_columns=["usuario_id"],
                        referred_table="usuarios",
                        referred_columns=["id"],
                    )
                ],
            )
        ],
        enums=[EnumSchema(name="estado_usuario", values=["activo", "inactivo"])],
    )

    diff = provider.diff(current, desired)

    assert diff.has_changes() is True
    details = "\n".join(change.details for change in diff.changes)
    assert "cambiará de tipo" in details
    assert "cambiará nullable" in details
    assert "Se agregará la columna 'email'" in details
    assert "existe hoy en 'usuarios' pero no en el esquema deseado" in details
    assert "Se agregará el enum 'estado_usuario'" not in details
    assert "El enum 'estado_usuario' cambiará" in details
    assert "Se agregará la tabla 'perfiles'" in details


def test_sqlite_provider_disables_native_enums_in_introspection_logic() -> None:
    provider = SqlAlchemySqliteProvider()
    assert provider.supports_native_enums() is False


def test_postgres_provider_enables_native_enums_in_introspection_logic() -> None:
    provider = SqlAlchemyPostgresProvider()
    assert provider.supports_native_enums() is True


def test_project_can_resolve_metadata_from_import_path(monkeypatch, tmp_path: Path) -> None:
    import sys

    package_dir = tmp_path / "demo_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "metadata_module.py").write_text(
        "from sqlalchemy import MetaData\nmetadata = MetaData()\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(tmp_path))
    try:
        class ImportedMetadataProject(MigrationProject):
            def get_settings(self) -> MigrationProjectSettings:
                return MigrationProjectSettings(
                    project_name="imported",
                    migrations_dir=Path("."),
                    database_url="sqlite:///tmp.db",
                    metadata_import_path="demo_pkg.metadata_module:metadata",
                )

        project = ImportedMetadataProject()
        metadata = project.get_metadata()
        assert metadata is not None
        assert metadata.__class__.__name__ == "MetaData"
    finally:
        sys.path.remove(str(tmp_path))


def test_persistence_kit_registry_schema_source_builds_indexes_and_foreign_keys(tmp_path: Path) -> None:
    import types
    import sys

    package_dir = tmp_path / "fake_app"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "entities.py").write_text(
        "\n".join(
            [
                "from dataclasses import dataclass",
                "from uuid import UUID",
                "@dataclass(slots=True)",
                "class AcademicUnit:",
                "    id: UUID",
                "    name: str",
                "@dataclass(slots=True)",
                "class Course:",
                "    id: UUID",
                "    name: str",
                "    academic_unit_id: UUID",
                "    course_signature: str",
            ]
        ),
        encoding="utf-8",
    )
    (package_dir / "registry_setup.py").write_text(
        "\n".join(
            [
                "from persistence_kit.repository_factory.registry.entity_registry import register_entity, ENTITY_CONFIG",
                "from fake_app.entities import AcademicUnit, Course",
                "ENTITY_CONFIG.clear()",
                "def register_defaults():",
                "    register_entity('academic_unit', {'entity': AcademicUnit, 'collection': 'academic_units', 'unique': {'name': 'name'}})",
                "    register_entity('course', {'entity': Course, 'collection': 'courses', 'unique': {'course_signature': 'course_signature'}, 'relations': {'academic_unit': {'local_field': 'academic_unit_id', 'target': 'academic_unit', 'by': 'id', 'many': False}}})",
            ]
        ),
        encoding="utf-8",
    )
    sys.path.insert(0, str(tmp_path))
    fake_persistence_kit = types.ModuleType("persistence_kit")
    fake_repository_factory = types.ModuleType("persistence_kit.repository_factory")
    fake_registry_pkg = types.ModuleType("persistence_kit.repository_factory.registry")
    fake_entity_registry = types.ModuleType("persistence_kit.repository_factory.registry.entity_registry")
    fake_repository_module = types.ModuleType("persistence_kit.repository")
    fake_settings_pkg = types.ModuleType("persistence_kit.settings")
    fake_constants = types.ModuleType("persistence_kit.settings.constants")

    class FakeDatabase:
        MONGO = types.SimpleNamespace(value="mongo")

    entity_config: dict[str, dict] = {}

    def register_entity(key: str, config: dict) -> None:
        entity_config[key] = config

    def build_table_from_dataclass(entity_type, table_name: str, metadata: MetaData):
        columns = [Column("id", String(), nullable=False)]
        for field in dataclasses.fields(entity_type):
            if field.name == "id":
                continue
            columns.append(Column(field.name, String(), nullable=field.default is dataclasses.MISSING))
        return Table(table_name, metadata, *columns)

    fake_entity_registry.ENTITY_CONFIG = entity_config
    fake_entity_registry.register_entity = register_entity
    fake_repository_module.build_table_from_dataclass = build_table_from_dataclass
    fake_constants.Database = FakeDatabase

    original_modules = {name: sys.modules.get(name) for name in [
        "persistence_kit",
        "persistence_kit.repository",
        "persistence_kit.repository_factory",
        "persistence_kit.repository_factory.registry",
        "persistence_kit.repository_factory.registry.entity_registry",
        "persistence_kit.settings",
        "persistence_kit.settings.constants",
    ]}
    sys.modules["persistence_kit"] = fake_persistence_kit
    sys.modules["persistence_kit.repository"] = fake_repository_module
    sys.modules["persistence_kit.repository_factory"] = fake_repository_factory
    sys.modules["persistence_kit.repository_factory.registry"] = fake_registry_pkg
    sys.modules["persistence_kit.repository_factory.registry.entity_registry"] = fake_entity_registry
    sys.modules["persistence_kit.settings"] = fake_settings_pkg
    sys.modules["persistence_kit.settings.constants"] = fake_constants
    try:
        class RegistryProject(MigrationProject):
            def get_settings(self) -> MigrationProjectSettings:
                return MigrationProjectSettings(
                    project_name="registry-project",
                    migrations_dir=Path("."),
                    database_url="sqlite:///tmp.db",
                    provider_name="sqlalchemy-sqlite",
                )

            def get_schema_source(self):
                return PersistenceKitRegistrySchemaSource(
                    registry_initializer_import_path="fake_app.registry_setup:register_defaults"
                )

        snapshot = RegistryProject().get_schema_source().build_desired_schema(RegistryProject())
        tables = {table.name: table for table in snapshot.tables}
        assert "courses" in tables
        assert tables["courses"].column_coverage == "full"
        assert tables["courses"].lazy_materialization is True
        assert any(column.name == "academic_unit_id" for column in tables["courses"].columns)
        assert any(index.name == "uniq_course_signature_courses" for index in tables["courses"].indexes)
        assert any(foreign_key.referred_table == "academic_units" for foreign_key in tables["courses"].foreign_keys)
    finally:
        sys.path.remove(str(tmp_path))
        for module_name, original in original_modules.items():
            if original is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original


def test_review_reports_partial_coverage_for_tables_without_columns() -> None:
    class PartialSource(SchemaSource):
        name = "partial-source"

        def build_desired_schema(self, project: MigrationProject) -> SchemaSnapshot:
            return SchemaSnapshot(
                provider_name="sqlalchemy-sqlite",
                source_name=self.name,
                notes=["El esquema deseado fue construido con información parcial."],
                tables=[
                    TableSchema(
                        name="courses",
                        columns=[],
                        indexes=[IndexSchema(name="uniq_course_signature_courses", columns=["course_signature"], unique=True)],
                        foreign_keys=[ForeignKeySchema(name="fk_courses_academic_unit_id", constrained_columns=["academic_unit_id"], referred_table="academic_units", referred_columns=["id"])],
                        column_coverage="partial",
                        source_name=self.name,
                        notes=["No se pudieron inferir columnas desde la fuente actual."],
                    )
                ],
            )

    class PartialProject(MigrationProject):
        def get_settings(self) -> MigrationProjectSettings:
            return MigrationProjectSettings(
                project_name="partial-project",
                migrations_dir=Path("."),
                database_url="sqlite:///tmp.db",
                provider_name="sqlalchemy-sqlite",
            )

        def get_schema_source(self):
            return PartialSource()

        def get_provider(self):
            class StubProvider(SqlAlchemySqliteProvider):
                def inspect_current(self, project: MigrationProject) -> SchemaSnapshot:
                    return SchemaSnapshot(provider_name=self.name, tables=[], source_name="introspeccion")

            return StubProvider()

    review = MigrationRunner(PartialProject()).review()

    assert "Fuente del esquema deseado: partial-source" in review
    assert "Cobertura parcial detectada:" in review
    assert "Tabla 'courses' con cobertura de columnas 'partial'." in review
    assert "No se pudieron inferir columnas desde la fuente actual." in review


class SnapshotProvider(DatabaseProvider):
    name = "snapshot-provider"

    def __init__(self, current: SchemaSnapshot, desired: SchemaSnapshot, diff: SchemaDiff, *, revision: str | None = None) -> None:
        self._current = current
        self._desired = desired
        self._diff = diff
        self._revision = revision
        self.applied_revision: str | None | object = object()
        self.received_messages: list[str] = []

    def synth(self, project: MigrationProject) -> SchemaSnapshot:
        return self._desired

    def inspect_current(self, project: MigrationProject) -> SchemaSnapshot:
        return self._current

    def diff(self, current: SchemaSnapshot, desired: SchemaSnapshot) -> SchemaDiff:
        return self._diff

    def review(self, diff: SchemaDiff) -> str:
        if not diff.changes:
            return "No hay cambios."
        return "\n".join(change.details for change in diff.changes)

    def current(self, project: MigrationProject) -> None:
        return None

    def history(self, project: MigrationProject) -> None:
        return None

    def upgrade(self, project: MigrationProject, revision: str = "head") -> None:
        return None

    def downgrade(self, project: MigrationProject, revision: str) -> None:
        return None

    def stamp(self, project: MigrationProject, revision: str) -> None:
        return None

    def get_current_revision(self, project: MigrationProject) -> str | None:
        return "base"

    def apply_revision(self, project: MigrationProject, revision: str | None) -> None:
        self.applied_revision = revision

    def create_revision_from_snapshots(
        self,
        project: MigrationProject,
        *,
        message: str,
        current: SchemaSnapshot,
        desired: SchemaSnapshot,
        diff: SchemaDiff,
    ) -> str | None:
        self.received_messages.append(message)
        return self._revision


class SnapshotProject(MigrationProject):
    def __init__(self, root: Path, provider: SnapshotProvider) -> None:
        self._root = root
        self._provider = provider

    def get_settings(self) -> MigrationProjectSettings:
        return MigrationProjectSettings(
            project_name="snapshot-project",
            migrations_dir=self._root / "migrations",
            database_url="sqlite:///tmp.db",
            provider_name=self._provider.name,
        )

    def get_provider(self) -> DatabaseProvider:
        return self._provider


def test_runner_snapshot_crud_persists_revision_and_lazy_tables(tmp_path: Path) -> None:
    current = SchemaSnapshot(provider_name="snapshot-provider", source_name="current")
    desired = SchemaSnapshot(
        provider_name="snapshot-provider",
        source_name="desired-source",
        notes=["Snapshot deseada."],
        tables=[
            TableSchema(
                name="schedule_courses",
                lazy_materialization=True,
                notes=["Tabla materializada de forma lazy."],
            )
        ],
    )
    diff = SchemaDiff(
        provider_name="snapshot-provider",
        changes=[
            SchemaChange(
                change_type="pendiente",
                object_type="tabla-lazy",
                object_name="schedule_courses",
                details="La tabla 'schedule_courses' todavía no existe físicamente.",
            )
        ],
    )
    provider = SnapshotProvider(current, desired, diff, revision="abc123")
    runner = MigrationRunner(SnapshotProject(tmp_path, provider))

    snapshot_path = runner.create_snapshot("Baseline Inicial")
    payload = runner.show_snapshot("v001-baseline-inicial")
    listed = runner.list_snapshots()

    assert snapshot_path.name == "v001-baseline-inicial.json"
    assert provider.received_messages == ["v001-baseline-inicial"]
    assert payload["alembic_revision"] == "abc123"
    assert payload["desired_snapshot"]["tables"][0]["lazy_materialization"] is True
    assert listed == [
        {
            "version_id": "v001-baseline-inicial",
            "created_at": payload["created_at"],
            "label": "Baseline Inicial",
            "path": str(snapshot_path),
            "project_name": "snapshot-project",
            "alembic_revision": "abc123",
        }
    ]

    deleted_path = runner.delete_snapshot("v001-baseline-inicial")

    assert deleted_path == str(snapshot_path)
    assert snapshot_path.exists() is False


def test_runner_apply_snapshot_resolves_base_revision_as_none(tmp_path: Path) -> None:
    provider = SnapshotProvider(
        SchemaSnapshot(provider_name="snapshot-provider"),
        SchemaSnapshot(provider_name="snapshot-provider"),
        SchemaDiff(provider_name="snapshot-provider"),
        revision=None,
    )
    runner = MigrationRunner(SnapshotProject(tmp_path, provider))

    snapshot_path = runner.create_snapshot("baseline")
    applied_revision = runner.apply_snapshot("v001-baseline")

    assert snapshot_path.exists() is True
    assert applied_revision == "base"
    assert provider.applied_revision is None


def test_runner_apply_snapshot_uses_specific_revision(tmp_path: Path) -> None:
    provider = SnapshotProvider(
        SchemaSnapshot(provider_name="snapshot-provider"),
        SchemaSnapshot(provider_name="snapshot-provider"),
        SchemaDiff(provider_name="snapshot-provider"),
        revision="rev_002",
    )
    runner = MigrationRunner(SnapshotProject(tmp_path, provider))

    runner.create_snapshot("after-phone")
    applied_revision = runner.apply_snapshot("v001-after-phone")

    assert applied_revision == "rev_002"
    assert provider.applied_revision == "rev_002"


def test_postgres_provider_marks_missing_lazy_tables_as_pending() -> None:
    provider = SqlAlchemyPostgresProvider()
    current = SchemaSnapshot(provider_name=provider.name, tables=[])
    desired = SchemaSnapshot(
        provider_name=provider.name,
        tables=[
            TableSchema(
                name="schedule_courses",
                lazy_materialization=True,
                notes=["Tabla materializada de forma lazy."],
            )
        ],
    )

    diff = provider.diff(current, desired)

    assert diff.changes == [
        SchemaChange(
            change_type="pendiente",
            object_type="tabla-lazy",
            object_name="schedule_courses",
            details="La tabla 'schedule_courses' todavía no existe físicamente. Esto puede ser esperable si persistence_kit la materializa de forma lazy hasta el primer uso del repositorio.",
        )
    ]
