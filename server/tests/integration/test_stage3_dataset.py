from dokura.stage3_dataset import generate


def test_representative_dataset_uses_stage3_indexes(tmp_path) -> None:
    result = generate(tmp_path / "scale.sqlite3", 1_000)
    assert result["records"] == 1_000
    assert "ix_files_parent_name" in result["query_plans"]["parent_name"]
    assert "VIRTUAL TABLE INDEX" in result["query_plans"]["fts"]
