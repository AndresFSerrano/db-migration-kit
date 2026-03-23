from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from db_migration_kit.bootstrap import bootstrap_project
from db_migration_kit.inspector import inspect_project
from db_migration_kit.loader import load_project
from db_migration_kit.runner import MigrationRunner
from db_migration_kit.scaffold import initialize_project_scaffold


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="db-migration-kit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Inicializa la estructura base del proyecto de migraciones")
    init_parser.add_argument("--root", default=".", help="Directorio raiz")
    init_parser.add_argument("--project-name", required=True, help="Nombre logico del proyecto")
    init_parser.add_argument("--class-name", default="ProjectMigration", help="Nombre de la clase del proyecto")

    inspect_parser = subparsers.add_parser("inspect-project", help="Escanea el proyecto y propone configuración de migraciones")
    inspect_parser.add_argument("--root", default=".", help="Directorio raiz")

    bootstrap_parser = subparsers.add_parser("bootstrap", help="Escanea el proyecto y genera archivos mínimos de migración")
    bootstrap_parser.add_argument("--root", default=".", help="Directorio raiz")
    bootstrap_parser.add_argument("--class-name", default="ProjectMigration", help="Nombre de la clase del proyecto")

    snapshot_create_parser = subparsers.add_parser("snapshot-create", help="Crea una snapshot versionada del esquema esperado y su diff")
    snapshot_create_parser.add_argument("--project-module", required=True, help="Modulo Python que expone 'project'")
    snapshot_create_parser.add_argument("--label", help="Etiqueta opcional para la snapshot")

    snapshot_list_parser = subparsers.add_parser("snapshot-list", help="Lista snapshots versionadas del proyecto")
    snapshot_list_parser.add_argument("--project-module", required=True, help="Modulo Python que expone 'project'")

    snapshot_show_parser = subparsers.add_parser("snapshot-show", help="Muestra una snapshot versionada existente")
    snapshot_show_parser.add_argument("--project-module", required=True, help="Modulo Python que expone 'project'")
    snapshot_show_parser.add_argument("--version-id", required=True, help="Identificador de snapshot, por ejemplo v001 o v001-baseline")

    snapshot_delete_parser = subparsers.add_parser("snapshot-delete", help="Borra una snapshot versionada existente")
    snapshot_delete_parser.add_argument("--project-module", required=True, help="Modulo Python que expone 'project'")
    snapshot_delete_parser.add_argument("--version-id", required=True, help="Identificador de snapshot, por ejemplo v001 o v001-baseline")

    snapshot_apply_parser = subparsers.add_parser("snapshot-apply", help="Aplica una snapshot versionada usando Alembic por detras")
    snapshot_apply_parser.add_argument("--project-module", required=True, help="Modulo Python que expone 'project'")
    snapshot_apply_parser.add_argument("--version-id", required=True, help="Identificador de snapshot, por ejemplo v001 o v001-baseline")

    snapshot_rollback_parser = subparsers.add_parser("snapshot-rollback", help="Vuelve a una snapshot versionada usando Alembic por detras")
    snapshot_rollback_parser.add_argument("--project-module", required=True, help="Modulo Python que expone 'project'")
    snapshot_rollback_parser.add_argument("--version-id", required=True, help="Identificador de snapshot, por ejemplo v001 o v001-baseline")

    for name in ("doctor", "current", "history", "synth", "diff", "review"):
        command_parser = subparsers.add_parser(name)
        command_parser.add_argument("--project-module", required=True, help="Modulo Python que expone 'project'")

    upgrade_parser = subparsers.add_parser("upgrade")
    upgrade_parser.add_argument("--project-module", required=True, help="Modulo Python que expone 'project'")
    upgrade_parser.add_argument("--revision", default="head")

    downgrade_parser = subparsers.add_parser("downgrade")
    downgrade_parser.add_argument("--project-module", required=True, help="Modulo Python que expone 'project'")
    downgrade_parser.add_argument("--revision", required=True)

    stamp_parser = subparsers.add_parser("stamp")
    stamp_parser.add_argument("--project-module", required=True, help="Modulo Python que expone 'project'")
    stamp_parser.add_argument("--revision", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        created = initialize_project_scaffold(
            Path(args.root),
            project_name=args.project_name,
            class_name=args.class_name,
        )
        for path in created:
            print(path)
        return 0
    if args.command == "inspect-project":
        print(inspect_project(Path(args.root)).to_json())
        return 0
    if args.command == "bootstrap":
        inspection, created = bootstrap_project(Path(args.root))
        print(inspection.to_json())
        for path in created:
            print(path)
        return 0

    runner = MigrationRunner(load_project(args.project_module))

    if args.command == "snapshot-create":
        print(runner.create_snapshot(label=args.label))
        return 0
    if args.command == "snapshot-list":
        print(json.dumps(runner.list_snapshots(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "snapshot-show":
        print(json.dumps(runner.show_snapshot(args.version_id), ensure_ascii=False, indent=2))
        return 0
    if args.command == "snapshot-delete":
        print(runner.delete_snapshot(args.version_id))
        return 0
    if args.command == "snapshot-apply":
        revision = runner.apply_snapshot(args.version_id)
        print(f"snapshot={args.version_id}")
        print(f"revision={revision}")
        return 0
    if args.command == "snapshot-rollback":
        revision = runner.apply_snapshot(args.version_id)
        print(f"snapshot={args.version_id}")
        print(f"revision={revision}")
        return 0

    if args.command == "doctor":
        for key, value in runner.doctor().items():
            print(f"{key}={value}")
        return 0
    if args.command == "synth":
        print(runner.snapshot_as_json(runner.synth()))
        return 0
    if args.command == "diff":
        diff = runner.diff()
        print(runner.diff_as_json(diff))
        return 1 if diff.has_changes() else 0
    if args.command == "review":
        print(runner.review())
        return 0
    if args.command == "current":
        runner.current()
        return 0
    if args.command == "history":
        runner.history()
        return 0
    if args.command == "upgrade":
        runner.upgrade(args.revision)
        return 0
    if args.command == "downgrade":
        runner.downgrade(args.revision)
        return 0
    if args.command == "stamp":
        runner.stamp(args.revision)
        return 0

    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
