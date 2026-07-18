from dokura.stage3_dataset import generate


def test_representative_dataset_uses_stage3_indexes(tmp_path) -> None:
    result = generate(tmp_path / "scale.sqlite3", 1_000)
    assert result["records"] == 1_000
    assert "ix_files_parent_name" in result["query_plans"]["parent_name"]
    assert "VIRTUAL TABLE INDEX" in result["query_plans"]["fts"]


def test_representative_dataset_can_match_scan_fixtures(tmp_path) -> None:
    content = tmp_path / "Content"
    result = generate(tmp_path / "scale.sqlite3", 12, content)
    assert result["filesystem_fixtures"] == 12
    assert len(list(content.rglob("*.zip"))) == 12
    assert all(path.read_bytes().startswith(b"PK") for path in content.rglob("*.zip"))
