# Tagger

![badge](https://img.shields.io/badge/Powered_By-GPT--5.6--Sol-orange.svg?style=for-the-badge&logo=data:image/svg%2bxml;base64,PHN2ZyB2aWV3Qm94PSIwIDAgNTEyIDUxMiIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiIGNsaXAtcnVsZT0iZXZlbm9kZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIgc3Ryb2tlLW1pdGVybGltaXQ9IjIiIHN0cm9rZT0iI2ZmZmZmZiIgZmlsbD0iI2ZmZmZmZiI+PHBhdGggZD0iTTQ3NC4xMjMgMjA5LjgxYzExLjUyNS0zNC41NzcgNy41NjktNzIuNDIzLTEwLjgzOC0xMDMuOTA0LTI3LjY5Ni00OC4xNjgtODMuNDMzLTcyLjk0LTEzNy43OTQtNjEuNDE0YTEyNy4xNCAxMjcuMTQgMCAwMC05NS40NzUtNDIuNDljLTU1LjU2NCAwLTEwNC45MzYgMzUuNzgxLTEyMi4xMzkgODguNTkzLTM1Ljc4MSA3LjM5Ny02Ni41NzQgMjkuNzYtODQuNjM3IDYxLjQxNC0yNy44NjggNDguMTY3LTIxLjUwMyAxMDguNzIgMTUuODI2IDE1MC4wMDctMTEuNTI1IDM0LjU3OC03LjU2OSA3Mi40MjQgMTAuODM4IDEwMy43MzMgMjcuNjk2IDQ4LjM0IDgzLjQzMyA3My4xMTEgMTM3Ljk2NiA2MS41ODUgMjQuMDg0IDI3LjE4IDU4LjgzMyA0Mi44MzUgOTUuMzAzIDQyLjY2MyA1NS41NjQgMCAxMDQuOTM2LTM1Ljc4MiAxMjIuMTM5LTg4LjU5NCAzNS43ODItNy4zOTcgNjYuNTc0LTI5Ljc2IDg0LjQ2NS02MS40MTMgMjguMDQtNDguMTY4IDIxLjY3Ni0xMDguNzIyLTE1LjY1NC0xNTAuMDA4di0uMTcyem0tMzkuNTY3LTg3LjIxOGMxMS4wMSAxOS4yNjcgMTUuMTM5IDQxLjgwMyAxMS4zNTQgNjMuNjUtLjY4OC0uNTE2LTIuMDY0LTEuMjA0LTIuOTI0LTEuNzJsLTEwMS4xNTItNTguNDlhMTYuOTY1IDE2Ljk2NSAwIDAwLTE2LjY4NyAwTDIwNi42MjEgMTk0LjV2LTUwLjIzMmw5Ny44ODMtNTYuNTk3YzQ1LjU4Ny0yNi4zMiAxMDMuNzMyLTEwLjY2NiAxMzAuMDUyIDM0LjkyMXptLTIyNy45MzUgMTA0LjQybDQ5Ljg4OC0yOC45IDQ5Ljg4NyAyOC45djU3LjYzbC00OS44ODcgMjguOS00OS44ODgtMjguOXYtNTcuNjN6bTIzLjIyMy0xOTEuODFjMjIuMzY0IDAgNDMuODY3IDcuNzQyIDYxLjA3IDIyLjAyLS42ODguMzQ0LTIuMDY0IDEuMjA0LTMuMDk3IDEuNzJMMTg2LjY2NiAxMTcuMjZjLTUuMTYxIDIuOTI1LTguMjU4IDguNDMtOC4yNTggMTQuNDV2MTM2LjkzNGwtNDMuNTIzLTI1LjExNlYxMzAuMzMzYzAtNTIuNjQgNDIuNDkxLTk1LjEzIDk1LjEzMS05NS4zMDJsLS4xNzIuMTcyek01Mi4xNCAxNjguNjk3YzExLjE4Mi0xOS4yNjggMjguNTU3LTM0LjA2MiA0OS41NDQtNDEuODAzVjI0Ny4xNGMwIDYuMDIgMy4wOTcgMTEuMzU0IDguMjU4IDE0LjQ1bDExOC4zNTQgNjguMjk1LTQzLjY5NSAyNS4yODgtOTcuNzExLTU2LjQyNWMtNDUuNDE1LTI2LjMyLTYxLjA3LTg0LjQ2NS0zNC43NS0xMzAuMDUyem0yNi42NjUgMjIwLjcxYy0xMS4xODItMTkuMDk1LTE1LjEzOS00MS44MDItMTEuMzU0LTYzLjY1LjY4OC41MTYgMi4wNjQgMS4yMDQgMi45MjQgMS43MmwxMDEuMTUyIDU4LjQ5YTE2Ljk2NSAxNi45NjUgMCAwMDE2LjY4NyAwbDExOC4zNTQtNjguNDY3djUwLjIzMmwtOTcuODgzIDU2LjQyNWMtNDUuNTg3IDI2LjE0OC0xMDMuNzMyIDEwLjY2NS0xMzAuMDUyLTM0Ljc1aC4xNzJ6bTIwNC41NCA4Ny4zOWMtMjIuMTkyIDAtNDMuODY3LTcuNzQxLTYwLjg5OC0yMi4wMmE2Mi40MzkgNjIuNDM5IDAgMDAzLjA5Ny0xLjcybDEwMS4xNTItNTguMzE3YzUuMTYtMi45MjQgOC40MjktOC40MyA4LjI1Ny0xNC40NVYyNDMuNTI3bDQzLjUyMyAyNS4xMTZ2MTEzLjAyMmMwIDUyLjY0LTQyLjY2MyA5NS4zMDMtOTUuMTMxIDk1LjMwM3YtLjE3MnpNNDYxLjIyIDM0My4zMDNjLTExLjE4MiAxOS4yNjctMjguNzI5IDM0LjA2MS00OS41NDQgNDEuNjNWMjY0LjY4N2MwLTYuMDIxLTMuMDk3LTExLjUyNi04LjI1Ny0xNC40NUwyODQuODkzIDE4MS43N2w0My41MjMtMjUuMTE2IDk3Ljg4MyA1Ni40MjRjNDUuNTg3IDI2LjMyIDYxLjA3IDg0LjQ2NiAzNC43NSAxMzAuMDUzbC4xNzIuMTcyeiIgZmlsbC1ydWxlPSJub256ZXJvIiAvPjwvc3ZnPg==)

An image tagging app based on PySide6, intended to assist in small-scale image dataset processing, specifically LoRA datasets.

## Install

[uv](https://docs.astral.sh/uv/) is required

```sh
$ git clone https://github.com/MoveToEx/tagger.git
$ cd tagger
$ uv sync --all-groups    # if AI tagging or VAE preview is needed
$ uv sync                 # without model-backed features
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

### Scripting

For scripting, there's a helper class `TagSet` that extends `set[str]` with utilities that may help:

- `in` operator takes a wildcard pattern (only `*` is supported) and checks if any tag in the set matches the pattern.
- `.matching(str)` method accepts a wildcard pattern and yields every tag in the set that matches the pattern.

You can opt out from using `TagSet` and keep `set[str]` in settings dialog if you want.

#### Complex filter

_Tags_ > _Complex Filter_ allows you to write custom Python scripts to filter out images with complex conditions.  

The script contains a `check(fn: str, tags: TagSet) -> bool` function, which accepts the file name (relative to the open folder) and the tag set of an image. Images that `check` function returns `True` will be collected into the result table.  
Double clicking on one row will focus the image in the main window.

#### Bulk operation

_Tags_ > _Bulk Operation_ allows you to programmatically apply changes to images' tags.  

The script contains a `process(fn: str, tags: TagSet) -> set[str]` function which returns the new list of tags.  
After running all images through the script, the results are compared against the original ones to calculate the difference, and you need to review the differences image-by-image.


#### Pixel transform

_Image_ > _Pixel Transform_ allows you to programmatically edit image data.  

The script contains a `transform(pixels: np.array) -> np.array` function that receives the image data and returns the new image data.  
The first selected image is used to calculate preview image to help you debug.  
Note that channel data are passed as 0-255 integers rather than floating numbers.

Might be helpful for some alpha channel operations.

### Image actions

#### Deduplicate

_Image_ > _Deduplicate_ finds similar images in the checked folders and images, and asks you to review for deletion.  
Pairs involving images already marked for deletion are skipped.  

#### Mask editor

_Image_ > _Mask Editor_ allows you to edit the transparency (alpha) channel of images. Existing transparency data is dropped as it's hard to infer polygon data from 2d array.  

This was initially designed for training with masked loss combined with alpha mask.  

#### Crop

_Image_ > _Crop_ allows you to crop the image according to ARB settings or a specific aspect ratio.  

In ARB mode, it finds one bucket with the closest aspect ratio, and upscales proportionally to fit the image.  

Respects global ARB settings.

#### VAE preview

_Image_ > _VAE Preview_ encodes the current image with VAE and decodes it back to pixels, so as to show how it looks if it were generated entirely by the model. It should 

This step could be slow on some machines and is generally not necessary.  

#### Grid preview

_Image_ > _Grid Preview_ visualizes what an image looks like and how large a DiT token occupies when it's used for training. It scales and crops the image according your training parameters, and overlays a grid over the current image so each cell represents a DiT token.  

Try to make your training target take more cells so the model understands it better.  

### Tag editing

#### Traversal

_Tags_ > _Add Tags_/_Delete Tags_ allows you to add tags to or delete tags from open folders and decide on a one-by-one basis.   
_Tags_ > _Toggle Tags_ combines the two.  

Adding/Deleting tags will ask you for the image to act on and a list of tags. When traversing, you need to decide on which one to add or delete for each image-tag pair. Tags already present/absent will be ignored. 

Decisions are committed only when you click on finish button, and are saved to memory whenever it is changed (i.e. whenever you toggle a tag).  
You can use <kbd>Space</kbd> to toggle a tag, <kbd>↑</kbd>/<kbd>↓</kbd> to select between tags, <kbd>←</kbd>/<kbd>→</kbd>/<kbd>Enter</kbd> to navigate between images (this is purely navigational and does not affect in-memory decision store), and <kbd>A</kbd> to select/deselect all tags.

#### Review

_Tags_ > _Review Tags_ allows you to thoroughly review tags within a folder and determine whether they should be deleted one-by-one.  

Decisions are stored in memory and are committed only when the revision finishes.  

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

#### Correlation analysis

_Tags_ > _Correlation Analysis_ takes a tag and finds other tags that are possibly correlated to it.  
For a given tag `s` and every other tag `t`, it calculates the following:

$$
\frac{\text{images with both }s\text{ and t}}{\text{images with }t}
$$

For concept LoRAs, try to avoid correlating your activation tag with an unrelated tag.

## Code layout

`main.py` starts the application through `tagger/app.py`.

```text
tagger/
  domain/          Image models, tag operations, traversal and review sessions
  ai_tagging/      Dependency checks, model caching/downloads, inference and dialogs
  vae_preview/     VAE child-process controller and worker
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
