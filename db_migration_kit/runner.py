from __future__ import annotations

import json
from pathlib import Path

from db_migration_kit.project import MigrationProject
from db_migration_kit.schema import SchemaDiff, SchemaSnapshot, TableSchema
from db_migration_kit.snapshots import (
    build_snapshot_payload,
    ensure_snapshots_dir,
    list_snapshots,
    next_version_id,
)


class MigrationRunner:
    def __init__(self, project: MigrationProject) -> None:
        self._project = project
        self._settings = project.get_settings()
        self._settings.validate()
        self._provider = project.get_provider()

    def doctor(self) -> dict[str, str]:
        return {
            "project_name": self._settings.project_name,
            "provider_name": self._settings.provider_name,
            "migrations_dir": str(self._settings.normalized_migrations_dir()),
            "alembic_ini_path": str(self._settings.normalized_alembic_ini_path()),
            "snapshots_dir": str(self._settings.normalized_snapshots_dir()),
            "version_table": self._settings.version_table,
            "metadata_import_path": self._settings.metadata_import_path or "",
        }

    def synth(self) -> SchemaSnapshot:
        return self._provider.synth(self._project)

    def inspect_current(self) -> SchemaSnapshot:
        return self._provider.inspect_current(self._project)

    def diff(self) -> SchemaDiff:
        current = self.inspect_current()
        desired = self.synth()
        return self._provider.diff(current, desired)

    def review(self) -> str:
        current = self.inspect_current()
        desired = self.synth()
        diff = self._provider.diff(current, desired)
        lines: list[str] = [self._provider.review(diff)]

        source_name = desired.source_name or "desconocido"
        lines.append("")
        lines.append(f"Fuente del esquema deseado: {source_name}")
        for note in desired.notes:
            lines.append(f"- {note}")

        partial_tables = [table for table in desired.tables if table.column_coverage != "full"]
        if partial_tables:
            lines.append("")
            lines.append("Cobertura parcial detectada:")
            for table in partial_tables:
                lines.extend(self._format_partial_table_warning(table))

        return "\n".join(lines)

    @staticmethod
    def _format_partial_table_warning(table: TableSchema) -> list[str]:
        lines = [
            f"- Tabla '{table.name}' con cobertura de columnas '{table.column_coverage}'.",
            "  El review de columnas, tipos, nullability y defaults puede ser incompleto para esta tabla.",
        ]
        if table.indexes:
            lines.append(f"  Señal confiable disponible: índices={len(table.indexes)}.")
        if table.foreign_keys:
            lines.append(f"  Señal confiable disponible: foreign_keys={len(table.foreign_keys)}.")
        for note in table.notes:
            lines.append(f"  Nota: {note}")
        return lines

    def current(self) -> None:
        self._provider.current(self._project)

    def history(self) -> None:
        self._provider.history(self._project)

    def upgrade(self, revision: str = "head") -> None:
        self._provider.upgrade(self._project, revision)

    def downgrade(self, revision: str) -> None:
        self._provider.downgrade(self._project, revision)

    def stamp(self, revision: str) -> None:
        self._provider.stamp(self._project, revision)

    def create_snapshot(self, label: str | None = None) -> Path:
        current = self.inspect_current()
        desired = self.synth()
        diff = self._provider.diff(current, desired)
        review = self.review()
        snapshots_dir = ensure_snapshots_dir(self._settings.normalized_snapshots_dir())
        version_id = next_version_id(snapshots_dir, label=label)
        target_revision = self._provider.create_revision_from_snapshots(
            self._project,
            message=version_id,
            current=current,
            desired=desired,
            diff=diff,
        )
        payload = build_snapshot_payload(
            version_id=version_id,
            label=label,
            project_name=self._settings.project_name,
            provider_name=self._settings.provider_name,
            alembic_revision=target_revision,
            review=review,
            diff=json.loads(self.diff_as_json(diff)),
            desired_snapshot=json.loads(self.snapshot_as_json(desired)),
        )
        snapshot_path = snapshots_dir / f"{version_id}.json"
        snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return snapshot_path

    def list_snapshots(self) -> list[dict[str, str]]:
        return [
            {
                "version_id": record.version_id,
                "created_at": record.created_at,
                "label": record.label or "",
                "path": str(record.path),
                "project_name": record.project_name or "",
                "alembic_revision": record.alembic_revision or "base",
            }
            for record in list_snapshots(self._settings.normalized_snapshots_dir())
        ]

    def show_snapshot(self, version_id: str) -> dict:
        snapshots_dir = self._settings.normalized_snapshots_dir()
        candidates = list_snapshots(snapshots_dir)
        for record in candidates:
            if record.version_id == version_id:
                return json.loads(record.path.read_text(encoding="utf-8"))
        raise ValueError(f"No existe snapshot '{version_id}' en {snapshots_dir}")

    def apply_snapshot(self, version_id: str) -> str:
        payload = self.show_snapshot(version_id)
        revision = payload.get("alembic_revision")
        self._provider.apply_revision(self._project, None if revision == "base" else revision)
        return str(revision or "base")

    def delete_snapshot(self, version_id: str) -> str:
        snapshots_dir = self._settings.normalized_snapshots_dir()
        candidates = list_snapshots(snapshots_dir)
        for record in candidates:
            if record.version_id != version_id:
                continue
            record.path.unlink(missing_ok=False)
            return str(record.path)
        raise ValueError(f"No existe snapshot '{version_id}' en {snapshots_dir}")

    @staticmethod
    def snapshot_as_json(snapshot: SchemaSnapshot) -> str:
        return json.dumps(
            {
                "provider_name": snapshot.provider_name,
                "tables": [
                    {
                        "name": table.name,
                        "column_coverage": table.column_coverage,
                        "source_name": table.source_name,
                        "lazy_materialization": table.lazy_materialization,
                        "notes": table.notes,
                        "columns": [
                            {
                                "name": column.name,
                                "type_name": column.type_name,
                                "nullable": column.nullable,
                                "default": column.default,
                                "enum_values": column.enum_values,
                            }
                            for column in table.columns
                        ],
                        "indexes": [
                            {
                                "name": index.name,
                                "columns": index.columns,
                                "unique": index.unique,
                            }
                            for index in table.indexes
                        ],
                        "foreign_keys": [
                            {
                                "name": foreign_key.name,
                                "constrained_columns": foreign_key.constrained_columns,
                                "referred_table": foreign_key.referred_table,
                                "referred_columns": foreign_key.referred_columns,
                            }
                            for foreign_key in table.foreign_keys
                        ],
                    }
                    for table in snapshot.tables
                ],
                "enums": [
                    {
                        "name": enum_schema.name,
                        "values": enum_schema.values,
                    }
                    for enum_schema in snapshot.enums
                ],
                "source_name": snapshot.source_name,
                "notes": snapshot.notes,
            },
            ensure_ascii=False,
            indent=2,
        )

    @staticmethod
    def diff_as_json(diff: SchemaDiff) -> str:
        return json.dumps(
            {
                "provider_name": diff.provider_name,
                "changes": [
                    {
                        "change_type": change.change_type,
                        "object_type": change.object_type,
                        "object_name": change.object_name,
                        "details": change.details,
                    }
                    for change in diff.changes
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
