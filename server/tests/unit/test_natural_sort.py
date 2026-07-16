from dokura.metadata.natural_sort import natural_path_key, natural_sort_bytes, normalized_casefold


def test_path_aware_natural_sort_is_stable() -> None:
    names = ["Page10.JPG", "folder/2.jpg", "page2.jpg", "folder/10.jpg", "PAGE2.jpg"]
    assert sorted(names, key=natural_path_key) == ["folder/2.jpg", "folder/10.jpg", "PAGE2.jpg", "page2.jpg", "Page10.JPG"]


def test_nfc_casefold_normalization() -> None:
    assert normalized_casefold("CAFÉ") == normalized_casefold("cafe\u0301")


def test_persisted_key_preserves_natural_order() -> None:
    names = ["10.jpg", "2.jpg", "1.jpg"]
    assert sorted(names, key=natural_sort_bytes) == ["1.jpg", "2.jpg", "10.jpg"]


def test_file_sorts_before_same_named_directory_contents() -> None:
    names = ["1.jpg/2.jpg", "1.jpg"]
    assert sorted(names, key=natural_path_key) == ["1.jpg", "1.jpg/2.jpg"]
    assert sorted(names, key=natural_sort_bytes) == ["1.jpg", "1.jpg/2.jpg"]
