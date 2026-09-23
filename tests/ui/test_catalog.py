from __future__ import annotations

from pathlib import Path

from tagger.domain.models import ImageEntry
from tagger.ui.catalog import ImageCatalogModel


def test_folder_items_show_recursive_dataset_percentages(qtbot, tmp_path: Path) -> None:
    model = ImageCatalogModel()
    entries = [
        ImageEntry(tmp_path / "animals" / "cat.png", tmp_path / "cat.txt"),
        ImageEntry(tmp_path / "animals" / "dog.png", tmp_path / "dog.txt"),
        ImageEntry(
            tmp_path / "animals" / "birds" / "owl.png", tmp_path / "owl.txt"
        ),
        ImageEntry(tmp_path / "plants" / "tree.png", tmp_path / "tree.txt"),
        ImageEntry(tmp_path / "house.png", tmp_path / "house.txt"),
    ]

    model.set_entries(entries, tmp_path)

    animals = model.invisibleRootItem().child(0)
    plants = model.invisibleRootItem().child(1)
    assert animals is not None
    assert plants is not None
    assert animals.text() == "animals"
    assert plants.text() == "plants"
    assert animals.child(0).text() == "birds"
    assert animals.data(model.FolderPercentageRole) == 60.0
    assert plants.data(model.FolderPercentageRole) == 20.0
    assert animals.child(0).data(model.FolderPercentageRole) == 20.0
    assert animals.toolTip() == "animals"
    assert animals.data(model.FolderRole) == str(tmp_path / "animals")
