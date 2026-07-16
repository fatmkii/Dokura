from collections.abc import Iterator
from pathlib import Path

import pytest

from dokura.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Iterator[Settings]:
    content = tmp_path / "content"
    metadata = tmp_path / "metadata"
    config = tmp_path / "config"
    content.mkdir()
    yield Settings(content_dir=content, metadata_dir=metadata, config_dir=config)
