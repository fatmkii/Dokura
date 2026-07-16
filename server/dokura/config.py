from dataclasses import dataclass
from os import environ
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    content_dir: Path
    metadata_dir: Path
    config_dir: Path

    @property
    def database_path(self) -> Path:
        return self.metadata_dir / "dokura.sqlite3"

    @property
    def cover_dir(self) -> Path:
        return self.metadata_dir / "covers"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            content_dir=Path(environ.get("DOKURA_CONTENT_DIR", "/data/content")),
            metadata_dir=Path(environ.get("DOKURA_METADATA_DIR", "/data/metadata")),
            config_dir=Path(environ.get("DOKURA_CONFIG_DIR", "/data/config")),
        )

    def prepare(self) -> None:
        for label, path in (("MetaData", self.metadata_dir), ("Config", self.config_dir)):
            try:
                path.mkdir(parents=True, exist_ok=True)
                probe = path / ".dokura-write-check"
                probe.touch()
                probe.unlink()
            except OSError as exc:
                raise RuntimeError(f"{label} 目录不可写: {path}: {exc}") from exc
