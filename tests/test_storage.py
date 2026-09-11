from __future__ import annotations


import shutil
import zipfile
from pathlib import Path

import pytest

from tagger.domain.models import ImageEntry
from tagger.storage import (
    archive_entries,
    BatchPreflightError,
    duplicate_image_pair,
    ExternalChangeError,
    WriteRequest,
    find_unrecognized_files,
    move_image_pair,
    rename_image_pair,
    scan_folder,
    write_tags_atomic,
    write_tags_batch,
)


IMAGE_EXTENSIONS = {".jpg", ".png"}


def touch_image(path: Path) -> None:
    path.write_bytes(b"not decoded by scanner")


def test_find_unrecognized_files_keeps_supported_images_and_sidecars(
    tmp_path: Path,
) -> None:
    touch_image(tmp_path / "sample.JPG")
    (tmp_path / "sample.txt").write_text("cat\n", encoding="utf-8")
    (tmp_path / "sample.JPG.txt").write_text("cat\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    touch_image(nested / "child.png")
    (nested / "child.txt").write_text("dog\n", encoding="utf-8")
    unknown = tmp_path / "notes.json"
    unknown.write_text("{}", encoding="utf-8")
    nested_unknown = nested / "preview.webp.txt"
    nested_unknown.write_text("preview", encoding="utf-8")

    assert find_unrecognized_files(tmp_path, IMAGE_EXTENSIONS) == [
        unknown,
        tmp_path / "sample.JPG.txt",
        nested_unknown,
    ]


def test_scan_creates_sidecars_for_nested_images(tmp_path: Path) -> None:
    touch_image(tmp_path / "one.JPG")
    nested = tmp_path / "nested"
    nested.mkdir()
    touch_image(nested / "two.jpg")

    result = scan_folder(tmp_path, IMAGE_EXTENSIONS)

    entries = {
        entry.image_path.relative_to(tmp_path).as_posix(): entry
        for entry in result.entries
    }
    assert sorted(entries) == ["nested/two.jpg", "one.JPG"]
    assert entries["one.JPG"].tag_path == tmp_path / "one.txt"
    assert entries["nested/two.jpg"].tag_path == nested / "two.txt"
    assert (tmp_path / "one.txt").read_text(encoding="utf-8") == "\n"
    assert (nested / "two.txt").read_text(encoding="utf-8") == "\n"


def test_scan_allows_same_names_in_different_subfolders(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    touch_image(first / "sample.jpg")
    touch_image(second / "sample.jpg")
    (first / "sample.txt").write_text("first", encoding="utf-8")
    (second / "sample.txt").write_text("second", encoding="utf-8")

    result = scan_folder(tmp_path, IMAGE_EXTENSIONS)

    entries = {
        entry.image_path.relative_to(tmp_path).as_posix(): entry
        for entry in result.entries
    }
    assert entries["first/sample.jpg"].tags == ["first"]
    assert entries["second/sample.jpg"].tags == ["second"]


def test_scan_keeps_images_from_each_folder_contiguous(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    touch_image(tmp_path / "a.jpg")
    touch_image(nested / "b.jpg")
    touch_image(tmp_path / "z.jpg")

    result = scan_folder(tmp_path, IMAGE_EXTENSIONS)

    assert [
        entry.image_path.relative_to(tmp_path).as_posix()
        for entry in result.entries
    ] == ["a.jpg", "z.jpg", "nested/b.jpg"]


def test_scan_prefers_stem_then_falls_back_to_full_name(tmp_path: Path) -> None:
    touch_image(tmp_path / "a.jpg")
    (tmp_path / "a.txt").write_text("stem", encoding="utf-8")
    (tmp_path / "a.jpg.txt").write_text("full", encoding="utf-8")
    touch_image(tmp_path / "b.png")
    (tmp_path / "b.png.txt").write_text("full-only", encoding="utf-8")

    result = scan_folder(tmp_path, IMAGE_EXTENSIONS)
    entries = {entry.image_path.name: entry for entry in result.entries}

    assert entries["a.jpg"].tag_path.name == "a.txt"
    assert entries["a.jpg"].tags == ["stem"]
    assert "ignored" in entries["a.jpg"].warnings[0]
    assert entries["b.png"].tag_path.name == "b.png.txt"


def test_scan_excludes_duplicate_stems(tmp_path: Path) -> None:
    touch_image(tmp_path / "same.jpg")
    touch_image(tmp_path / "same.png")

    result = scan_folder(tmp_path, IMAGE_EXTENSIONS)

    assert result.entries == []
    assert "duplicate image stems" in result.issues[0].message
    assert not (tmp_path / "same.txt").exists()


def test_scan_excludes_cross_form_sidecar_collision(tmp_path: Path) -> None:
    touch_image(tmp_path / "foo.jpg")
    touch_image(tmp_path / "foo.jpg.png")
    (tmp_path / "foo.jpg.txt").write_text("shared", encoding="utf-8")

    result = scan_folder(tmp_path, IMAGE_EXTENSIONS)

    assert result.entries == []
    assert any("same sidecar" in issue.message for issue in result.issues)


def test_invalid_utf8_sidecar_is_visible_but_read_only(tmp_path: Path) -> None:
    touch_image(tmp_path / "bad.jpg")
    (tmp_path / "bad.txt").write_bytes(b"\xff")

    entry = scan_folder(tmp_path, IMAGE_EXTENSIONS).entries[0]

    assert not entry.editable
    assert "UTF-8" in (entry.error or "")


def test_rename_image_pair_renames_both_files(tmp_path: Path) -> None:
    image_path = tmp_path / "old.PNG"
    tag_path = tmp_path / "old.txt"
    touch_image(image_path)
    tag_path.write_bytes(b"cat\n")
    entry = ImageEntry(image_path, tag_path)

    new_image_path, new_tag_path = rename_image_pair(entry, "new name")

    assert new_image_path == tmp_path / "new name.PNG"
    assert new_tag_path == tmp_path / "new name.txt"
    assert new_image_path.read_bytes() == b"not decoded by scanner"
    assert new_tag_path.read_bytes() == b"cat\n"
    assert not image_path.exists()
    assert not tag_path.exists()


def test_rename_image_pair_rejects_collision_without_changes(tmp_path: Path) -> None:
    image_path = tmp_path / "old.png"
    tag_path = tmp_path / "old.txt"
    touch_image(image_path)
    tag_path.write_bytes(b"cat\n")
    touch_image(tmp_path / "taken.png")

    with pytest.raises(FileExistsError, match="taken.png"):
        rename_image_pair(ImageEntry(image_path, tag_path), "taken")

    assert image_path.exists()
    assert tag_path.read_bytes() == b"cat\n"


def test_rename_image_pair_rejects_path_separator(tmp_path: Path) -> None:
    image_path = tmp_path / "old.png"
    tag_path = tmp_path / "old.txt"
    touch_image(image_path)
    tag_path.write_bytes(b"cat\n")

    with pytest.raises(ValueError, match="path separators"):
        rename_image_pair(ImageEntry(image_path, tag_path), "nested/name")

    assert image_path.exists()
    assert tag_path.exists()


def test_rename_image_pair_rolls_back_when_sidecar_rename_fails(
    tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "old.png"
    tag_path = tmp_path / "old.txt"
    touch_image(image_path)
    tag_path.write_bytes(b"cat\n")
    original_rename = Path.rename

    def fail_for_sidecar(path: Path, target: Path) -> Path:
        if path == tag_path:
            raise PermissionError("sidecar is locked")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_for_sidecar)

    with pytest.raises(OSError, match="Could not rename old.txt"):
        rename_image_pair(ImageEntry(image_path, tag_path), "new")

    assert image_path.exists()
    assert tag_path.exists()
    assert not (tmp_path / "new.png").exists()
    assert not (tmp_path / "new.txt").exists()


def test_move_image_pair_moves_both_files_without_renaming(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    image_path = source / "sample.PNG"
    tag_path = source / "sample.PNG.txt"
    touch_image(image_path)
    tag_path.write_bytes(b"cat\n")

    new_image_path, new_tag_path = move_image_pair(
        ImageEntry(image_path, tag_path), destination
    )

    assert new_image_path == destination / "sample.PNG"
    assert new_tag_path == destination / "sample.PNG.txt"
    assert new_image_path.read_bytes() == b"not decoded by scanner"
    assert new_tag_path.read_bytes() == b"cat\n"
    assert not image_path.exists()
    assert not tag_path.exists()


def test_move_image_pair_rejects_collision_without_changes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    image_path = source / "sample.png"
    tag_path = source / "sample.txt"
    touch_image(image_path)
    tag_path.write_bytes(b"cat\n")
    (destination / "SAMPLE.PNG").write_bytes(b"existing")

    with pytest.raises(FileExistsError, match="sample.png"):
        move_image_pair(ImageEntry(image_path, tag_path), destination)

    assert image_path.exists()
    assert tag_path.read_bytes() == b"cat\n"
    assert (destination / "SAMPLE.PNG").read_bytes() == b"existing"
    assert not (destination / "sample.txt").exists()


def test_move_image_pair_rolls_back_when_sidecar_move_fails(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    image_path = source / "sample.png"
    tag_path = source / "sample.txt"
    touch_image(image_path)
    tag_path.write_bytes(b"cat\n")
    original_rename = Path.rename

    def fail_for_sidecar(path: Path, target: Path) -> Path:
        if path == tag_path:
            raise PermissionError("sidecar is locked")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_for_sidecar)

    with pytest.raises(OSError, match="Could not move sample.txt"):
        move_image_pair(ImageEntry(image_path, tag_path), destination)

    assert image_path.exists()
    assert tag_path.exists()
    assert not (destination / "sample.png").exists()
    assert not (destination / "sample.txt").exists()


def test_duplicate_image_pair_copies_both_files_with_fixed_suffix(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "sample.PNG"
    tag_path = tmp_path / "sample.txt"
    touch_image(image_path)
    tag_path.write_bytes(b"cat\n")

    new_image_path, new_tag_path = duplicate_image_pair(
        ImageEntry(image_path, tag_path)
    )

    assert new_image_path == tmp_path / "sample_2.PNG"
    assert new_tag_path == tmp_path / "sample_2.txt"
    assert new_image_path.read_bytes() == image_path.read_bytes()
    assert new_tag_path.read_bytes() == tag_path.read_bytes()


def test_duplicate_image_pair_rejects_collision_without_changes(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    touch_image(image_path)
    tag_path.write_bytes(b"cat\n")
    existing = tmp_path / "sample_2.PNG"
    existing.write_bytes(b"existing")

    with pytest.raises(FileExistsError, match="sample_2.png"):
        duplicate_image_pair(ImageEntry(image_path, tag_path))

    assert existing.read_bytes() == b"existing"
    assert not (tmp_path / "sample_2.txt").exists()


def test_duplicate_image_pair_rolls_back_when_sidecar_copy_fails(
    tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    touch_image(image_path)
    tag_path.write_bytes(b"cat\n")
    original_copyfileobj = shutil.copyfileobj
    calls = 0

    def fail_for_sidecar(source, destination) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("sidecar is locked")
        original_copyfileobj(source, destination)

    monkeypatch.setattr(shutil, "copyfileobj", fail_for_sidecar)

    with pytest.raises(OSError, match="Could not duplicate sample.txt"):
        duplicate_image_pair(ImageEntry(image_path, tag_path))

    assert image_path.exists()
    assert tag_path.exists()
    assert not (tmp_path / "sample_2.png").exists()
    assert not (tmp_path / "sample_2.txt").exists()


def test_archive_entries_stores_nested_pairs_with_unique_flat_names(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "archive.zip"
    first = source / "first"
    second = source / "second"
    first.mkdir(parents=True)
    second.mkdir()
    touch_image(first / "sample.jpg")
    touch_image(second / "sample.jpg")
    (first / "sample.txt").write_bytes(b"first tags\n")
    (second / "sample.txt").write_bytes(b"second tags\n")
    entries = scan_folder(source, IMAGE_EXTENSIONS).entries

    result = archive_entries(entries, destination)

    assert result.archived == [
        ("sample.jpg", "sample.txt"),
        ("sample_1.jpg", "sample_1.txt"),
    ]
    with zipfile.ZipFile(destination) as archive:
        assert archive.namelist() == [
            "sample.jpg",
            "sample.txt",
            "sample_1.jpg",
            "sample_1.txt",
        ]
        assert archive.read("sample.txt") == b"first tags\n"
        assert archive.read("sample_1.txt") == b"second tags\n"


def test_archive_entries_reports_current_file_and_progress(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    touch_image(source / "sample.png")
    (source / "sample.txt").write_bytes(b"tags\n")
    entry = scan_folder(source, IMAGE_EXTENSIONS).entries[0]
    progress: list[tuple[int, int, str]] = []

    archive_entries(
        [entry],
        tmp_path / "archive.zip",
        lambda completed, total, name: progress.append(
            (completed, total, name)
        ),
    )

    assert progress == [
        (0, 2, "sample.png"),
        (1, 2, "sample.png"),
        (1, 2, "sample.txt"),
        (2, 2, "sample.txt"),
    ]


def test_archive_entries_replaces_existing_archive_atomically(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "archive.zip"
    source.mkdir()
    touch_image(source / "sample.png")
    (source / "sample.txt").write_bytes(b"new tags\n")
    destination.write_bytes(b"old archive contents")
    entry = scan_folder(source, IMAGE_EXTENSIONS).entries[0]

    result = archive_entries([entry], destination)

    assert result.archived == [("sample.png", "sample.txt")]
    with zipfile.ZipFile(destination) as archive:
        assert archive.read("sample.png") == b"not decoded by scanner"
        assert archive.read("sample.txt") == b"new tags\n"


def test_archive_entries_leaves_destination_unchanged_for_missing_pair(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    touch_image(source / "sample.png")
    entry = scan_folder(source, IMAGE_EXTENSIONS).entries[0]
    entry.tag_path.unlink()
    destination = tmp_path / "archive.zip"
    destination.write_bytes(b"existing archive")

    with pytest.raises(FileNotFoundError, match="Tag file does not exist"):
        archive_entries([entry], destination)

    assert destination.read_bytes() == b"existing archive"


def test_atomic_write_detects_external_change(tmp_path: Path) -> None:
    path = tmp_path / "tags.txt"
    path.write_bytes(b"cat\n")

    with pytest.raises(ExternalChangeError):
        write_tags_atomic(path, ["dog"], expected_bytes=b"old\n")

    assert path.read_bytes() == b"cat\n"


def test_batch_preflight_failure_writes_nothing(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_bytes(b"a\n")
    second.write_bytes(b"changed\n")
    requests = [
        WriteRequest(first, ["x"], b"a\n"),
        WriteRequest(second, ["y"], b"b\n"),
    ]

    with pytest.raises(BatchPreflightError):
        write_tags_batch(requests)

    assert first.read_bytes() == b"a\n"
    assert second.read_bytes() == b"changed\n"
