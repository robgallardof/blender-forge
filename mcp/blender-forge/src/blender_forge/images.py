"""Contact sheets and previews the agent can look at."""
from pathlib import Path

from PIL import Image, ImageDraw


def preview(path, max_side=1024):
    """Downscaled PNG next to the original, so the agent gets a small image."""
    src = Path(path)
    with Image.open(src) as im:
        im = im.convert("RGBA")
        im.thumbnail((max_side, max_side))
        out = src.with_name(src.stem + "-preview.png")
        im.save(out)
    return out


def contact_sheet(views, out_path, cell=384):
    """Grid of labelled views: [{"view": "front", "path": ".../front.png"}, ...]."""
    cols = 2 if len(views) <= 4 else 3
    rows = (len(views) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * (cell + 24)), (24, 26, 32))
    draw = ImageDraw.Draw(sheet)
    for i, item in enumerate(views):
        with Image.open(item["path"]) as im:
            im = im.convert("RGBA")
            im.thumbnail((cell, cell))
            x, y = (i % cols) * cell, (i // cols) * (cell + 24)
            backdrop = Image.new("RGBA", im.size, (40, 44, 52, 255))
            backdrop.alpha_composite(im)
            sheet.paste(backdrop.convert("RGB"), (x + (cell - im.width) // 2, y + 24))
            draw.text((x + 8, y + 5), item["view"], fill=(220, 224, 232))
    out = Path(out_path)
    sheet.save(out)
    return out
