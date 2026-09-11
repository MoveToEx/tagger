# Tagger

An image tagging app based on PySide6, intended to assist in small-scale image dataset processing, specifically LoRA datasets.

## Install

[uv](https://docs.astral.sh/uv/) is required

```sh
$ git clone https://github.com/MoveToEx/tagger.git
$ cd tagger
$ uv sync --all-groups    # if AI tagging is needed
$ uv sync                 # if AI tagging is not needed
$ uv run python ./main.py
```

You may want to alter the CUDA accelerator to use in the pyproject.toml:

```toml
[[tool.uv.index]]
name = "pytorch-cu130"
url = "https://download.pytorch.org/whl/cu130"
explicit = true

[tool.uv.sources]
torch = [
    { index = "pytorch-cu130" },
]
torchvision = [
    { index = "pytorch-cu130" },
]
```

After modifying, use `uv lock` to re-lock the dependencies, and use `uv sync --all-groups` to sync the venv with the lockfile.

## Usage

Start by opening a directory containing images of supported format (PNG/JPG/WEBP) and tags (should be named `{image_stem}.txt` or `{image_full}.txt`, ignored when conflicting). Supports drag & drop. 

The application stores its settings in `data/settings.json` and the downloaded
binary tag library in `data/tag-lib/danbooru_tags.bin`. Set
`TAGGER_DATA_DIRECTORY` to use a different data directory.

> [!NOTE]
> It is assumed that users are training caption-based LoRAs and will randomly shuffle tags during training. Therefore, this app does not keep the tag order and stores tags in a `set[str]`. It might not work well if you're training an order-aware model.

#### Add/Delete traversal

_Tags_ > _Add Tags_/_Delete Tags_ allows you to add tags to or delete tags from open folders and decide on a one-by-one basis.   

Adding/Deleting tags will ask you for the image to act on and a list of tags. When traversing, you need to decide on which one to add or delete for each image-tag pair. Tags already present/absent will be ignored. 

Decisions are committed only when you click on finish button, and are saved to memory whenever it is changed (i.e. whenever you toggle a tag).  
You can use <kbd>Space</kbd> to toggle a tag, <kbd>↑</kbd>/<kbd>↓</kbd> to select between tags, <kbd>←</kbd>/<kbd>→</kbd>/<kbd>Enter</kbd> to navigate between images (this is purely navigational and does not affect in-memory decision store), and <kbd>A</kbd> to select/deselect all tags.

#### Complex filter

_Tags_ > _Complex Filter_ allows you to write custom Python scripts to filter out images with complex conditions.  

The script contains a `check(fn: str, tags: set[str]) -> bool` function, which accepts the file name (relative to the open folder) and the tag list of an image. Images that the function returns `True` will be collected into a result table. Double clicking on one row will focus the image in the main window.

#### Bulk operation

_Tags_ > _Bulk Operation_ allows you to programmatically apply changes to images' tags.  

The script contains a `process(fn: str, tags: set[str]) -> set[str]` function which returns the new list of tags. After running all images through the script, the results are compared against the original ones to calculate the difference, and you need to review the differences image-by-image. 

#### Tag review

_Tags_ > _Review Tags_ allows you to thoroughly review tags within a folder and determine whether they should be deleted one-by-one.  

Decisions are stored in memory and are committed only when the revision finishes.  

#### Deduplicate

_Image_ > _Deduplicate_ finds similar images in the checked folders and images.
Choose a perceptual-hash distance threshold: Exact (0), Very similar (1),
Similar (2), or Speculative (4). Exact compares perceptual hashes, not file bytes.

Review each pair side by side and choose Keep Left, Keep Right, or Keep Both.
Previous and Next only navigate; saved choices can be revisited and changed.
Pairs involving images already marked for deletion are skipped. Finish is
available at any point during review and moves marked images and their tag files
to the system Recycle Bin, keeping undecided images. Cancel discards the choices
without deleting files.

To permanently delete duplicates instead, enable _Deduplicate_ under
_Settings_ > _General_ > _Behavior_ > _Use unlink for..._.

The catalog click-and-hold behavior can also be set under _Settings_ >
_General_ > _Behavior_: choose _Drag and drop_ to move images between folders,
or _Navigate_ to change the selected image without moving files.

#### AI tagging

_Tags_ > _AI Tagging_ allows you to tag images with AI models.  

This requires the `ai-tagger` dependency group to be installed. If not, the menu item will be disabled.  

To use AI tagging, select and download models in the settings window.  
This app recognizes models from both hf cache folder and local `data/model` folder, so you can also download models using hf-cli outside of the app.  

After selecting images and inference parameters the app will start inference in a
separate process. The process exits after inference so PyTorch, the model, and GPU
memory are released before review begins. Model loading makes the preparation step
take longer each time inference is run.

After inference completes, you are supposed to check tags one by one. You can use shortcuts from the traversal window here.

## Code layout

`main.py` starts the application through `tagger/app.py`.

```text
tagger/
  domain/          Image models, tag operations, traversal and review sessions
  ai_tagging/      Dependency checks, model caching/downloads, inference and dialogs
  settings/        JSON storage, preferences, proxy configuration and settings UI
  tag_library/     Binary storage, search index, downloads and completion widgets
  ui/
    main_window/  Window layout/selection and controllers for actions and workflows
    dialogs/      Archive, filters, deduplication, search, review and traversal
    preview/      Background image loading and image display
    catalog.py    Qt image catalog model
    widgets.py    Shared widget sizing and painting helpers
  storage.py      Image/tag scanning and writes, renames and archives
  paths.py        Application data locations
  deduplication.py  Perceptual-hash matching
  trash.py        File deletion
tests/
  test_*.py       Domain and service tests
  ui/             Qt tests grouped by feature
```

The main window owns the widgets and current selection. Its controllers handle
menus and action state (`actions.py`), folder loading and recent folders
(`folders.py`), image file operations (`files.py`), tag editing (`tags.py`), and
launching feature dialogs (`dialogs.py`). Controllers keep a typed reference to
the window; imports used only for typing stay under `TYPE_CHECKING` to avoid
runtime cycles.

Import services from their implementation modules, such as
`tagger.settings.store` or `tagger.ai_tagging.inference`. Package exports for
domain models, settings and the tag library remain available without importing
their dialogs. Optional model runtimes such as PyTorch and timm are imported
only when model operations run.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Qt tests run with the offscreen platform plugin and do not require a visible
desktop session.
