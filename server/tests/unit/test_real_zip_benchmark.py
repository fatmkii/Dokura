import zipfile

from PIL import Image

from dokura.real_zip_benchmark import run, select_representative


def test_real_zip_benchmark_is_read_only(tmp_path) -> None:
    content = tmp_path / "content"
    content.mkdir()
    archive = content / "sample.zip"
    image = tmp_path / "page.jpg"
    Image.new("RGB", (32, 48), "red").save(image)
    with zipfile.ZipFile(archive, "w") as target:
        target.write(image, "page.jpg")
    before = archive.stat()
    result = run(content, 1, 1)
    after = archive.stat()
    assert result["all_unchanged"] is True
    assert result["results"][0]["page_count"] == 1
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)


def test_representative_selection_includes_size_extremes(tmp_path) -> None:
    for index, size in enumerate((10, 20, 30, 40, 50)):
        (tmp_path / f"{index}.zip").write_bytes(b"x" * size)
    selected = select_representative(tmp_path, 3)
    assert [item.stat().st_size for item in selected] == [10, 30, 50]
