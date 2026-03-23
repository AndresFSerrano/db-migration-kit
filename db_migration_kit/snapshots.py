from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class SnapshotRecord:
    version_id: str
    created_at: str
    path: Path
    label: str | None = None
    project_name: str | None = None
    alembic_revision: str | None = None


_SNAPSHOT_PATTERN = re.compile(r"^v(?P<number>\d{3})(?:-(?P<label>[a-z0-9-]+))?\.json$")


def ensure_snapshots_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_snapshots(path: Path) -> list[SnapshotRecord]:
    snapshots_dir = ensure_snapshots_dir(path)
    records: list[SnapshotRecord] = []
    for snapshot_path in sorted(snapshots_dir.glob("v*.json")):
        match = _SNAPSHOT_PATTERN.match(snapshot_path.name)
        if not match:
            continue
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        records.append(
            SnapshotRecord(
                version_id=str(payload.get("version_id") or snapshot_path.stem),
                created_at=str(payload.get("created_at") or ""),
                path=snapshot_path,
                label=payload.get("label"),
                project_name=payload.get("project_name"),
                alembic_revision=payload.get("alembic_revision"),
            )
        )
    return records


def next_version_id(path: Path, label: str | None = None) -> str:
    records = list_snapshots(path)
    next_number = 1
    if records:
        parsed_numbers = []
        for record in records:
            match = re.match(r"^v(\d{3})", record.version_id)
            if match:
                parsed_numbers.append(int(match.group(1)))
        if parsed_numbers:
            next_number = max(parsed_numbers) + 1
    version_id = f"v{next_number:03d}"
    if label:
        normalized = normalize_label(label)
        if normalized:
            version_id = f"{version_id}-{normalized}"
    return version_id


def normalize_label(label: str) -> str:
    lowered = label.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered).strip("-")
    return lowered


def build_snapshot_payload(
    *,
    version_id: str,
    label: str | None,
    project_name: str,
    provider_name: str,
    alembic_revision: str | None,
    review: str,
    diff: dict,
    desired_snapshot: dict,
) -> dict:
    return {
        "version_id": version_id,
        "label": label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_name": project_name,
        "provider_name": provider_name,
        "alembic_revision": alembic_revision or "base",
        "review": review,
        "diff": diff,
        "desired_snapshot": desired_snapshot,
    }
