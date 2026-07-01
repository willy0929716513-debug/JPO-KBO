"""Lightweight local model registry: versions trained models to disk with
metadata (metrics, feature list, training timestamp), so you can track
what's deployed, compare candidates, and roll back -- a minimal MLOps layer
that needs no external service (no MLflow server, no S3), just the local
filesystem, which is the right amount of infrastructure for a project this size.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.config import DATA_DIR

MODEL_REGISTRY_DIR = DATA_DIR / "models"
MODEL_REGISTRY_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ModelMetadata:
    name: str
    version: str
    created_at: str
    metrics: dict = field(default_factory=dict)
    feature_columns: list[str] = field(default_factory=list)
    is_champion: bool = False
    notes: str = ""


class ModelRegistry:
    def __init__(self, registry_dir: Path | None = None):
        self.registry_dir = registry_dir or MODEL_REGISTRY_DIR
        self.registry_dir.mkdir(parents=True, exist_ok=True)

    def _paths(self, name: str, version: str) -> tuple[Path, Path]:
        base = self.registry_dir / f"{name}__{version}"
        return base.with_suffix(".joblib"), base.with_suffix(".json")

    def save(self, name: str, model, metrics: dict, feature_columns: list[str],
              version: str | None = None, notes: str = "") -> ModelMetadata:
        import joblib

        version = version or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        model_path, meta_path = self._paths(name, version)

        joblib.dump(model, model_path)
        metadata = ModelMetadata(name=name, version=version,
                                  created_at=datetime.now(timezone.utc).isoformat(),
                                  metrics=metrics, feature_columns=feature_columns, notes=notes)
        meta_path.write_text(json.dumps(asdict(metadata), indent=2))
        return metadata

    def load(self, name: str, version: str):
        import joblib

        model_path, meta_path = self._paths(name, version)
        if not model_path.exists():
            raise FileNotFoundError(f"No model '{name}' version '{version}' in registry.")
        model = joblib.load(model_path)
        metadata = ModelMetadata(**json.loads(meta_path.read_text()))
        return model, metadata

    def list_versions(self, name: str) -> list[ModelMetadata]:
        metas = [ModelMetadata(**json.loads(p.read_text())) for p in sorted(self.registry_dir.glob(f"{name}__*.json"))]
        return sorted(metas, key=lambda m: m.created_at)

    def get_champion(self, name: str) -> ModelMetadata | None:
        for meta in self.list_versions(name):
            if meta.is_champion:
                return meta
        return None

    def promote(self, name: str, version: str) -> None:
        """Marks `version` as the champion, demoting any previous champion."""
        found = False
        for meta in self.list_versions(name):
            meta.is_champion = (meta.version == version)
            found = found or meta.is_champion
            _, meta_path = self._paths(name, meta.version)
            meta_path.write_text(json.dumps(asdict(meta), indent=2))
        if not found:
            raise FileNotFoundError(f"No model '{name}' version '{version}' to promote.")
