from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


@dataclass(slots=True)
class ProjectInspection:
    root: str
    project_name: str
    suggested_provider_name: str
    suggested_schema_source: str
    registry_initializer_import_path: str | None = None
    metadata_import_path: str | None = None
    settings_getter_import_path: str | None = None
    migration_module_name: str = "migration_project"
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def inspect_project(root: Path) -> ProjectInspection:
    resolved_root = root.resolve()
    pyproject_data = _load_pyproject(resolved_root / "pyproject.toml")
    project_name = _discover_project_name(resolved_root, pyproject_data)
    dependencies = _read_dependencies(pyproject_data)
    provider_name = _suggest_provider_name(dependencies, resolved_root)
    registry_initializer_import_path = _detect_registry_initializer(resolved_root)
    metadata_import_path = _detect_metadata_import_path(resolved_root)
    settings_getter_import_path = _detect_settings_getter(resolved_root)
    schema_source = _suggest_schema_source(registry_initializer_import_path, metadata_import_path, dependencies)

    notes: list[str] = []
    if registry_initializer_import_path:
        notes.append(f"Se detectó inicializador de registry: {registry_initializer_import_path}")
    if metadata_import_path:
        notes.append(f"Se detectó metadata candidata: {metadata_import_path}")
    if settings_getter_import_path:
        notes.append(f"Se detectó settings getter: {settings_getter_import_path}")
    if not registry_initializer_import_path and not metadata_import_path:
        notes.append("No se detectó registry ni metadata automáticamente; se usará scaffold mínimo.")
    if "persistence-kit" in dependencies:
        notes.append("El proyecto declara persistence-kit; se puede sugerir schema source basado en registry.")

    return ProjectInspection(
        root=str(resolved_root),
        project_name=project_name,
        suggested_provider_name=provider_name,
        suggested_schema_source=schema_source,
        registry_initializer_import_path=registry_initializer_import_path,
        metadata_import_path=metadata_import_path,
        settings_getter_import_path=settings_getter_import_path,
        notes=notes,
    )


def _load_pyproject(path: Path) -> dict:
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _discover_project_name(root: Path, pyproject_data: dict) -> str:
    tool = pyproject_data.get("tool", {})
    poetry = tool.get("poetry", {})
    raw_name = poetry.get("name")
    if isinstance(raw_name, str) and raw_name.strip():
        return raw_name.strip().replace("_", "-")
    return root.name.replace("_", "-")


def _read_dependencies(pyproject_data: dict) -> dict:
    tool = pyproject_data.get("tool", {})
    poetry = tool.get("poetry", {})
    dependencies = poetry.get("dependencies", {})
    return dependencies if isinstance(dependencies, dict) else {}


def _suggest_provider_name(dependencies: dict, root: Path) -> str:
    dep_names = {str(name).lower() for name in dependencies}
    if "asyncpg" in dep_names or "psycopg2" in dep_names or "psycopg" in dep_names:
        return "sqlalchemy-postgres"
    if "sqlite" in dep_names:
        return "sqlalchemy-sqlite"
    env_path = root / ".env"
    if env_path.exists():
        env_text = env_path.read_text(encoding="utf-8", errors="ignore").lower()
        if "postgres" in env_text:
            return "sqlalchemy-postgres"
        if "sqlite" in env_text:
            return "sqlalchemy-sqlite"
    return "sqlalchemy-sqlite"


def _detect_registry_initializer(root: Path) -> str | None:
    candidates = [
        root / "app" / "infrastructure" / "repository_factory" / "register_defaults.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            module_path = ".".join(candidate.relative_to(root).with_suffix("").parts)
            return f"{module_path}:register_defaults"
    return None


def _detect_metadata_import_path(root: Path) -> str | None:
    candidates = [
        root / "app" / "db" / "metadata.py",
        root / "app" / "infrastructure" / "db" / "metadata.py",
        root / "app" / "metadata.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            module_path = ".".join(candidate.relative_to(root).with_suffix("").parts)
            return f"{module_path}:metadata"
    return None


def _detect_settings_getter(root: Path) -> str | None:
    candidates = [
        root / "app" / "core" / "config.py",
        root / "app" / "config.py",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        if "def get_settings" not in text:
            continue
        module_path = ".".join(candidate.relative_to(root).with_suffix("").parts)
        return f"{module_path}:get_settings"
    return None


def _suggest_schema_source(
    registry_initializer_import_path: str | None,
    metadata_import_path: str | None,
    dependencies: dict,
) -> str:
    if registry_initializer_import_path and "persistence-kit" in {str(name).lower() for name in dependencies}:
        return "persistence-kit-registry"
    if metadata_import_path:
        return "sqlalchemy-metadata"
    return "sqlalchemy-metadata"
