from __future__ import annotations

import importlib

from db_migration_kit.project import MigrationProject


def load_project(module_path: str) -> MigrationProject:
    module = importlib.import_module(module_path)
    project = getattr(module, "project", None)
    if project is None:
        raise ValueError(f"El modulo '{module_path}' debe exponer un objeto llamado 'project'")
    if not isinstance(project, MigrationProject):
        raise ValueError(f"El objeto 'project' en '{module_path}' no implementa MigrationProject")
    return project
