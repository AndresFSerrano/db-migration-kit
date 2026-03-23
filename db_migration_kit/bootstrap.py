from __future__ import annotations

from pathlib import Path

from db_migration_kit.inspector import ProjectInspection, inspect_project
from db_migration_kit.scaffold import initialize_project_scaffold_from_inspection


def bootstrap_project(root: Path) -> tuple[ProjectInspection, list[Path]]:
    inspection = inspect_project(root)
    created = initialize_project_scaffold_from_inspection(root.resolve(), inspection=inspection)
    return inspection, created
