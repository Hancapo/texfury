# texfury

Fast image-to-DDS conversion and RAGE texture dictionary toolkit for Python.

Built on **bc7enc_rdo** + **ISPC bc7e** for high-quality BC1/BC3/BC4/BC5/BC7 compression, with support for uncompressed A8R8G8B8 textures. No DirectXTex dependency — a single native DLL handles everything.

## Features

- **BC1, BC3, BC4, BC5, BC7** block compression with adjustable quality (0.0–1.0)
- **A8R8G8B8** uncompressed 32-bit BGRA format
- **DDS** file read/write (legacy + DX10 extended headers)
- **Texture dictionaries** — create and extract `.wtd` (GTA IV) and `.ytd` (GTA V, GTA V gen9, RDR2)
- **Mipmap generation** with configurable minimum size
- **Automatic power-of-two resize** (sRGB-aware via stb_image_resize2)
- **Transparency detection** without manual pixel iteration
- **Pillow integration** — accept `PIL.Image` objects (Pillow is optional)
- **Batch operations** with progress callbacks
- **Zero Python dependencies** — Pillow is optional

## Installation

```bash
pip install texfury
```

> **Pillow** is optional. Install it (`pip install Pillow`) only if you want to use `Texture.from_pil()`, `Texture.to_pil()`, or `has_transparency_pil()`.

---

## Quick Start

### Convert a single image to DDS

```python
from texfury import Texture, BCFormat

tex = Texture.from_image("logo.png", format=BCFormat.BC7, quality=0.8)
tex.save_dds("logo.dds")
```

### Create a texture dictionary from a folder

```python
from texfury import create_dict_from_folder, BCFormat, Game

# GTA V (default)
create_dict_from_folder("my_textures/", "output.ytd")

# GTA IV
create_dict_from_folder("my_textures/", "output.wtd", game=Game.GTA4)

# GTA V gen9
create_dict_from_folder("my_textures/", "output.ytd", game=Game.GTA5_GEN9)

# RDR2
create_dict_from_folder("my_textures/", "output.ytd", game=Game.RDR2)
```

### Extract textures from a dictionary

```python
from texfury import extract_dict

extract_dict("vehicles.ytd", "extracted/")
# Auto-detects game from header
# Creates extracted/texture_name.dds for each texture
```

---

## API Reference

### `BCFormat` — Compression Formats

```python
from texfury import BCFormat
```

| Value | Name | Description |
|-------|------|-------------|
| `BCFormat.BC1` | DXT1 | RGB, 6:1 ratio. No alpha. Smallest files. |
| `BCFormat.BC3` | DXT5 | RGBA, 4:1 ratio. Full alpha channel. |
| `BCFormat.BC4` | ATI1 | Single channel (R), 4:1 ratio. Grayscale/height maps. |
| `BCFormat.BC5` | ATI2 | Two channels (RG), 4:1 ratio. Normal maps. |
| `BCFormat.BC7` | BC7 | RGBA, 4:1 ratio. Best quality, slowest to encode. |
| `BCFormat.A8R8G8B8` | Uncompressed | 32-bit BGRA. No compression, largest files. |

**Choosing a format:**

- **Opaque textures** (no transparency): `BC1` for speed/size, `BC7` for quality
- **Textures with alpha**: `BC3` or `BC7`
- **Normal maps**: `BC5`
- **Grayscale / height maps**: `BC4`
- **Must be pixel-perfect**: `A8R8G8B8`

> **GTA IV note:** Only `BC1`, `BC3`, and `A8R8G8B8` are supported. BC4, BC5, and BC7 are not available on that platform.

---

### `MipFilter` — Downsampling Filters

Controls how pixels are interpolated when generating mipmaps and resizing to power-of-two.

```python
from texfury import MipFilter
```

| Value | Description | Best for |
|-------|-------------|----------|
| `MipFilter.MITCHELL` | Balanced sharpness/smoothness (B=1/3, C=1/3). **Default.** | General-purpose |
| `MipFilter.BOX` | Simple pixel average. Fast, correct for exact 2:1 downscale. | Fast iteration |
| `MipFilter.TRIANGLE` | Bilinear interpolation. | Smooth gradients |
| `MipFilter.CATMULL_ROM` | Sharp cubic interpolation. | Preserving edges/detail |
| `MipFilter.CUBIC_BSPLINE` | Gaussian-like smoothing (B=1, C=0). | Maximum smoothness |
| `MipFilter.POINT` | Nearest-neighbor, no interpolation. | Pixel art |

---

### `Texture` — Core Texture Object

Every operation in texfury produces or consumes a `Texture` object.

#### Properties

```python
tex.width       # int — pixel width
tex.height      # int — pixel height
tex.format      # BCFormat — compression format
tex.mip_count   # int — number of mipmap levels
tex.name        # str — texture name (read/write)
tex.data        # bytes — raw pixel data (all mip levels concatenated)
```

#### Creating Textures

##### `Texture.from_image(source, *, format, quality, generate_mipmaps, min_mip_size, resize_to_pot, mip_filter, name)`

Load an image file and compress it.

```python
tex = Texture.from_image(
    "photo.png",
    format=BCFormat.BC7,            # default
    quality=0.7,                    # 0.0 = fastest, 1.0 = best quality
    generate_mipmaps=True,          # default
    min_mip_size=4,                 # smallest mip dimension (default: 4)
    resize_to_pot=True,             # auto-resize to power-of-two (default)
    mip_filter=MipFilter.MITCHELL,  # downsampling filter (default)
    name="my_texture",              # defaults to filename stem
)
```

**Supported image formats:** PNG, JPG/JPEG, TGA, BMP, PSD, WebP, GIF, HDR, PNM/PPM natively. With Pillow installed, any format Pillow supports (TIFF, ICO, EPS, etc.) works automatically as a fallback.

##### `Texture.from_bytes(data, *, format, quality, generate_mipmaps, min_mip_size, resize_to_pot, mip_filter, name)`

Load an image from in-memory bytes and compress it. Same parameters as `from_image`, but accepts raw file bytes instead of a path.

```python
import httpx
from texfury import Texture, BCFormat

resp = httpx.get("https://example.com/texture.png")
tex = Texture.from_bytes(resp.content, format=BCFormat.BC7, name="downloaded")
```

##### `Texture.from_pil(image, *, format, quality, generate_mipmaps, min_mip_size, resize_to_pot, mip_filter, name)`

Create from a Pillow `Image` object. Requires Pillow.

```python
from PIL import Image
from texfury import Texture, BCFormat

img = Image.open("photo.png")
tex = Texture.from_pil(img, format=BCFormat.BC3, quality=0.9)
tex.save_dds("result.dds")
```

##### `Texture.from_dds(source, *, name)`

Load an existing DDS file.

```python
tex = Texture.from_dds("existing.dds")
print(tex.format, tex.width, tex.height, tex.mip_count)
```

##### `Texture.from_raw(data, width, height, fmt, mip_count, mip_offsets, mip_sizes, name)`

Create from raw compressed pixel data (advanced / internal use).

```python
tex = Texture.from_raw(
    data=raw_bytes,
    width=256, height=256,
    fmt=BCFormat.BC7,
    mip_count=7,
    mip_offsets=[0, 65536, ...],
    mip_sizes=[65536, 16384, ...],
    name="custom",
)
```

#### Saving Textures

##### `tex.save_dds(path)`

Write to a DDS file.

```python
tex.save_dds("output.dds")
```

##### `tex.to_dds_bytes()`

Get the complete DDS file as `bytes` (useful for in-memory pipelines).

```python
dds_data = tex.to_dds_bytes()
```

#### Decompression

##### `tex.to_rgba(mip=0)`

Decompress a texture back to raw RGBA pixels. Works with all formats (BC1–BC7, A8R8G8B8).

```python
rgba_bytes, width, height = tex.to_rgba()      # mip 0 (full resolution)
rgba_bytes, width, height = tex.to_rgba(mip=2)  # mip level 2 (quarter resolution)
```

##### `tex.to_pil(mip=0)`

Decompress to a Pillow `Image` object. Requires Pillow.

```python
pil_image = tex.to_pil()
pil_image.save("preview.png")
```

#### Inspection

##### `Texture.inspect_dds(source)`

Read DDS metadata without loading pixel data.

```python
info = Texture.inspect_dds("texture.dds")
# {'name': 'texture', 'width': 512, 'height': 512, 'format': BCFormat.BC7,
#  'format_name': 'BC7', 'mip_count': 10, 'data_size': 349524}
```

#### Quality Metrics

##### `tex.quality_metrics(original_rgba)`

Compare a compressed texture against the original RGBA pixels. Returns PSNR (dB) and SSIM.

```python
from texfury import _native as native

img = native.load_image("photo.png")
original_rgba = native.image_pixels(img, native.image_width(img), native.image_height(img))
native.free_image(img)

tex = Texture.from_image("photo.png", format=BCFormat.BC1, quality=0.5)
metrics = tex.quality_metrics(original_rgba)
print(f"PSNR: {metrics['psnr_rgb']:.1f} dB")   # higher = better (40+ is good)
print(f"SSIM: {metrics['ssim']:.4f}")            # 1.0 = identical
```

#### Validation

##### `tex.validate()`

Check a texture for common issues. Returns a list of warning strings (empty = all good).

```python
warnings = tex.validate()
if warnings:
    for w in warnings:
        print(f"WARNING: {w}")
```

Checks: dimensions, power-of-two, minimum size for BC formats, mip count, data size, max dimensions, name.

---

### `suggest_format(has_alpha, *, normal_map, single_channel, quality_over_size)`

Auto-detect the best compression format based on image characteristics.

```python
from texfury import suggest_format, has_transparency

fmt = suggest_format(
    has_alpha=has_transparency("icon.png"),
    quality_over_size=True,  # True → BC7, False → BC1/BC3
)
# Also supports: normal_map=True → BC5, single_channel=True → BC4
```

---

### `Game` — Target Game

```python
from texfury import Game
```

| Value | Format | Extension | Description |
|-------|--------|-----------|-------------|
| `Game.GTA4` | RSC5 | `.wtd` | GTA IV. Only BC1, BC3, A8R8G8B8. |
| `Game.GTA5` | RSC7 v13 | `.ytd` | GTA V (Legacy). **Default.** |
| `Game.GTA5_GEN9` | RSC7 v5 | `.ytd` | GTA V Enhanced (gen9). |
| `Game.RDR2` | RSC8 | `.ytd` | Red Dead Redemption 2. |

The `Game` enum controls which binary format is used when building texture dictionaries. When loading or inspecting, the game is auto-detected from the file header.

---

### `ITD` — Internal Texture Dictionary

`ITD` is a generic abstraction over RAGE engine texture dictionary formats. The file extension denotes the architecture: `.wtd` for x32 (GTA IV), `.ytd` for x64 (GTA V, RDR2). `ITD` provides a single API for all of them.

#### Building

```python
from texfury import ITD, Texture, BCFormat, Game

# GTA V (default)
td = ITD()
td.add(Texture.from_image("diffuse.png", format=BCFormat.BC7))
td.add(Texture.from_image("normal.png", format=BCFormat.BC5))
td.save("my_vehicle.ytd")

# GTA IV — only BC1, BC3, A8R8G8B8
td = ITD(game=Game.GTA4)
td.add(Texture.from_image("diffuse.png", format=BCFormat.BC1))
td.save("my_vehicle.wtd")

# RDR2
td = ITD(game=Game.RDR2)
td.add(Texture.from_image("diffuse.png", format=BCFormat.BC7))
td.save("my_rdr2_vehicle.ytd")

print(len(td))    # number of textures
print(td.game)    # Game.GTA5, Game.GTA4, etc.
```

#### Loading and Iterating

```python
td = ITD.load("vehicles.ytd")  # auto-detects game from header
print(td.game)

for tex in td.textures:
    print(f"{tex.name}: {tex.width}x{tex.height} {tex.format.name} ({tex.mip_count} mips)")
```

#### Lookup, Replace, Remove

```python
td = ITD.load("vehicles.ytd")

if "body_d" in td:
    tex = td.get("body_d")

print(td.names())  # ['body_d', 'body_n', 'body_s']

new_tex = Texture.from_image("new_body_d.png", format=BCFormat.BC7)
td.replace("body_d", new_tex)
td.save("vehicles_patched.ytd")

td.remove("body_s")
```

#### Inspecting Without Loading Data

```python
info = ITD.inspect("vehicles.ytd")  # auto-detects game
for entry in info:
    print(f"{entry['name']}: {entry['width']}x{entry['height']} "
          f"{entry['format_name']} mips={entry['mip_count']} "
          f"size={entry['data_size']} bytes")
```

#### Extracting to DDS

```python
td = ITD.load("props.ytd")
for tex in td.textures:
    tex.save_dds(f"extracted/{tex.name}.dds")
```

**Important:** Texture names must be set before adding to a dictionary. Names are automatically set from filenames when using `from_image()` or `from_dds()`.

---

### Convenience Functions

#### `create_dict_from_folder(folder, output, *, game, format, quality, generate_mipmaps, min_mip_size, mip_filter, on_progress)`

Convert all images in a folder into a single texture dictionary. Also picks up `.dds` files.

```python
from texfury import create_dict_from_folder, BCFormat, Game

path = create_dict_from_folder(
    "textures/",
    "output.ytd",
    game=Game.RDR2,
    format=BCFormat.BC7,
    quality=0.8,
    on_progress=lambda i, total, name: print(f"[{i}/{total}] {name}"),
)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `folder` | — | Directory with image files |
| `output` | `<folder>.ytd` | Output path |
| `game` | `GTA5` | Target game (see `Game` enum) |
| `format` | `BC7` | Compression format for all textures |
| `quality` | `0.7` | Compression quality 0.0–1.0 |
| `generate_mipmaps` | `True` | Generate mipmap chain |
| `min_mip_size` | `4` | Minimum mip dimension |
| `mip_filter` | `MITCHELL` | Downsampling filter for mipmaps |
| `on_progress` | `None` | Callback `(current, total, name)` |

> `create_ytd_from_folder` is available as a backward-compatible alias.

#### `batch_convert(folder, output_dir, *, format, quality, generate_mipmaps, min_mip_size, mip_filter, on_progress)`

Convert all images in a folder to individual DDS files.

```python
from texfury import batch_convert, BCFormat

batch_convert(
    "raw_textures/",
    "dds_output/",
    format=BCFormat.BC3,
    quality=0.6,
    on_progress=lambda i, total, name: print(f"[{i}/{total}] {name}"),
)
```

#### `extract_dict(path, output_dir)`

Extract all textures from a texture dictionary into DDS files. Auto-detects game format.

```python
from texfury import extract_dict

extract_dict("vehicles.ytd")
# Creates vehicles/texture1.dds, vehicles/texture2.dds, ...

extract_dict("vehicles.ytd", "my_folder/")
```

> `extract_ytd` is available as a backward-compatible alias.

---

### Image Utilities

Standalone helper functions that work without compressing anything.

#### `has_transparency(source)`

Check if an image file has transparent pixels.

```python
from texfury import has_transparency

if has_transparency("icon.png"):
    print("Has transparency — use BC3 or BC7")
else:
    print("Fully opaque — BC1 is fine")
```

#### `is_power_of_two(width, height)`

Check if both dimensions are powers of two.

```python
from texfury import is_power_of_two

is_power_of_two(256, 512)   # True
is_power_of_two(300, 400)   # False
```

#### `next_power_of_two(value)`

Get the nearest power-of-two >= the given value.

```python
from texfury import next_power_of_two

next_power_of_two(100)   # 128
next_power_of_two(256)   # 256
next_power_of_two(500)   # 512
```

#### `pot_dimensions(width, height)`

Get power-of-two dimensions for a given size.

```python
from texfury import pot_dimensions

pot_dimensions(300, 400)   # (512, 512)
pot_dimensions(1920, 1080) # (2048, 2048)
```

#### `image_dimensions(source)`

Get width, height, and channel count of an image without full decompression.

```python
from texfury import image_dimensions

w, h, ch = image_dimensions("photo.png")
print(f"{w}x{h}, {ch} channels")
```

---

## Examples

### Auto-detect format with suggest_format

```python
from texfury import Texture, suggest_format, has_transparency

def smart_compress(path, quality=0.8):
    fmt = suggest_format(has_transparency(path))
    return Texture.from_image(path, format=fmt, quality=quality)

tex = smart_compress("my_texture.png")
tex.save_dds("my_texture.dds")
```

### Pillow pipeline: resize + overlay + compress

```python
from PIL import Image
from texfury import Texture, BCFormat

base = Image.open("base.png").resize((512, 512))
overlay = Image.open("overlay.png").resize((512, 512))
base.paste(overlay, (0, 0), overlay)

tex = Texture.from_pil(base, format=BCFormat.BC7, quality=0.9)
tex.save_dds("composited.dds")
```

### Build a texture dictionary with mixed formats

```python
from texfury import ITD, Texture, BCFormat

td = ITD()

# Opaque diffuse — BC1 is fine, smallest size
td.add(Texture.from_image("body_d.png", format=BCFormat.BC1, quality=0.7))

# Normal map — BC5 stores RG channels
td.add(Texture.from_image("body_n.png", format=BCFormat.BC5, quality=0.8))

# Specular with transparency — BC3
td.add(Texture.from_image("body_s.png", format=BCFormat.BC3, quality=0.7))

# Emissive — uncompressed for precision
td.add(Texture.from_image("body_e.png", format=BCFormat.A8R8G8B8))

td.save("body.ytd")
```

### Batch convert with progress bar (tqdm)

```python
from texfury import batch_convert, BCFormat
from tqdm import tqdm

pbar = None

def on_progress(i, total, name):
    global pbar
    if pbar is None:
        pbar = tqdm(total=total, desc="Converting")
    pbar.update(1)
    pbar.set_postfix(texture=name)

batch_convert("raw/", "dds/", format=BCFormat.BC7, on_progress=on_progress)
if pbar:
    pbar.close()
```

### Re-pack a texture dictionary with different compression

```python
from texfury import ITD, BCFormat

td = ITD.load("original.ytd")
new_td = ITD(game=td.game)

for tex in td.textures:
    rgba, w, h = tex.to_rgba()
    new_tex = Texture.from_bytes(rgba, format=BCFormat.BC7, quality=0.9, name=tex.name)
    new_td.add(new_tex)

new_td.save("repacked.ytd")
```

---

## Quality Guide

The `quality` parameter (0.0–1.0) maps to the encoder's internal quality levels:

| Range | Speed | Quality | Use case |
|-------|-------|---------|----------|
| 0.0–0.2 | Fastest | Low | Quick previews, testing |
| 0.3–0.5 | Fast | Medium | Development builds |
| 0.6–0.8 | Moderate | High | Production use (recommended) |
| 0.9–1.0 | Slow | Maximum | Final release, archival |

BC7 is the slowest format to encode but produces the best visual quality. For rapid iteration, use `BC1` or `BC3` at lower quality, then do a final pass with `BC7` at 0.8+.

---

## Limitations

- **Windows only** — the native DLL is compiled for x64 Windows with MSVC
- **Power-of-two textures** — texture dictionaries require POT dimensions; `resize_to_pot=True` handles this automatically
- **No BC2 / BC6H** — BC2 (DXT3) is rarely used; BC6H (HDR) may be added later
- **GTA IV format support** — only BC1, BC3, and A8R8G8B8 (no BC4/BC5/BC7)
- **Max texture size** — limited by available memory; typical textures are 256–2048px
