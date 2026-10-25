"""Generate OG preview images and home-screen icons for the newspaper site."""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont

from bcpi.config import DATA_DIR, PROJECT_ROOT

PAPER = (243, 239, 228)  # #F3EFE4
INK = (22, 20, 18)  # #161412
RED = (181, 18, 27)  # #B5121B
WHITE = (255, 255, 255)

WEB_DIR = PROJECT_ROOT / "web"
DOCS_DIR = PROJECT_ROOT / "docs"
FONTS_DIR = DATA_DIR / "fonts"
LOGO_CACHE = DATA_DIR / "cache" / "logos"

MONTHS = [
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
]

FONT_FILES = {
    "mast": "OldStandard-Bold.ttf",
    "italic": "OldStandard-Italic.ttf",
    "serif900": "RobotoSerif-900-cond.ttf",
    "serif700": "RobotoSerif-700-cond.ttf",
    "banner": "Archivo-900-italic-cond.ttf",
    "label": "Archivo-800-cond.ttf",
}

_FONT_SOURCES = {
    "OldStandard-Bold.ttf": (
        "https://github.com/google/fonts/raw/main/ofl/oldstandardtt/OldStandard-Bold.ttf",
        None,
    ),
    "OldStandard-Italic.ttf": (
        "https://github.com/google/fonts/raw/main/ofl/oldstandardtt/OldStandard-Italic.ttf",
        None,
    ),
    "RobotoSerif-900-cond.ttf": (
        "https://github.com/google/fonts/raw/main/ofl/robotoserif/RobotoSerif%5BGRAD%2Copsz%2Cwdth%2Cwght%5D.ttf",
        {"wght": 900, "wdth": 70, "opsz": 48, "GRAD": 0},
    ),
    "RobotoSerif-700-cond.ttf": (
        "https://github.com/google/fonts/raw/main/ofl/robotoserif/RobotoSerif%5BGRAD%2Copsz%2Cwdth%2Cwght%5D.ttf",
        {"wght": 700, "wdth": 70, "opsz": 24, "GRAD": 0},
    ),
    "Archivo-900-italic-cond.ttf": (
        "https://github.com/google/fonts/raw/main/ofl/archivo/Archivo-Italic%5Bwdth%2Cwght%5D.ttf",
        {"wght": 900, "wdth": 70},
    ),
    "Archivo-800-cond.ttf": (
        "https://github.com/google/fonts/raw/main/ofl/archivo/Archivo%5Bwdth%2Cwght%5D.ttf",
        {"wght": 800, "wdth": 75},
    ),
}


def _download(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "bcpi-brand-images/1.0"})
    with urlopen(request, timeout=60) as response:  # noqa: S310
        return response.read()


def ensure_fonts() -> Path:
    """Make sure the static font files used for rendering exist on disk."""
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    for name, (url, axes) in _FONT_SOURCES.items():
        dest = FONTS_DIR / name
        if dest.exists() and dest.stat().st_size > 1000:
            continue
        raw = _download(url)
        if axes is None:
            dest.write_bytes(raw)
            continue
        from fontTools.ttLib import TTFont
        from fontTools.varLib import instancer

        variable = FONTS_DIR / f"_tmp_{name}"
        variable.write_bytes(raw)
        font = TTFont(variable)
        partial = instancer.instantiateVariableFont(font, axes)
        partial.save(dest)
        variable.unlink(missing_ok=True)
    return FONTS_DIR


def _font(key: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONTS_DIR / FONT_FILES[key]
    return ImageFont.truetype(str(path), size=size)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> Tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _center_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    cx: float,
    cy: float,
    fill: Tuple[int, int, int],
) -> None:
    width, height = _text_size(draw, text, font)
    box = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - width / 2 - box[0], cy - height / 2 - box[1]), text, font=font, fill=fill)


def format_updated(iso: Optional[str]) -> str:
    if not iso:
        return ""
    try:
        stamp = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return f"{MONTHS[stamp.month - 1]} {stamp.day}, {stamp.year}"


def week_slug(season: int, week: int, postseason: bool = False) -> str:
    if postseason:
        return f"og-{season}-post.png"
    if week <= 0:
        return f"og-{season}-pre.png"
    return f"og-{season}-w{week}.png"


def _load_logo(url: Optional[str], size: int = 64) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if not url:
        return canvas
    LOGO_CACHE.mkdir(parents=True, exist_ok=True)
    digest = "".join(ch if ch.isalnum() else "_" for ch in url)[-80:]
    cache_path = LOGO_CACHE / f"{digest}.png"
    try:
        if cache_path.exists():
            raw = cache_path.read_bytes()
        else:
            raw = _download(url)
            cache_path.write_bytes(raw)
        logo = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:
        return canvas
    logo.thumbnail((size, size), Image.Resampling.LANCZOS)
    x = (size - logo.width) // 2
    y = (size - logo.height) // 2
    canvas.paste(logo, (x, y), logo)
    return canvas


def _draw_banner(draw: ImageDraw.ImageDraw, width: int, height: int, week_label: str) -> int:
    banner_h = 70
    draw.rectangle([0, 0, width, banner_h], fill=RED)
    left = _font("banner", 28)
    right = _font("label", 22)
    inset = 48
    left_text = "COLLEGE FOOTBALL EXTRA"
    right_text = week_label
    left_box = draw.textbbox((0, 0), left_text, font=left)
    right_box = draw.textbbox((0, 0), right_text, font=right)
    draw.text(
        (inset - left_box[0], (banner_h - (left_box[3] - left_box[1])) / 2 - left_box[1]),
        left_text,
        font=left,
        fill=WHITE,
    )
    draw.text(
        (
            width - inset - (right_box[2] - right_box[0]) - right_box[0],
            (banner_h - (right_box[3] - right_box[1])) / 2 - right_box[1],
        ),
        right_text,
        font=right,
        fill=WHITE,
    )
    return banner_h


def _draw_dateline(
    draw: ImageDraw.ImageDraw,
    y: int,
    width: int,
    season: int,
    edition: str,
    updated: str,
) -> int:
    margin = 48
    draw.rectangle([margin, y, width - margin, y + 4], fill=INK)
    y += 14
    label = _font("label", 18)
    italic = _font("italic", 28)
    left = f"{season} SEASON"
    mid = edition
    right = updated
    left_box = draw.textbbox((0, 0), left, font=label)
    mid_box = draw.textbbox((0, 0), mid, font=italic)
    right_box = draw.textbbox((0, 0), right, font=label)
    row_h = max(left_box[3] - left_box[1], mid_box[3] - mid_box[1], right_box[3] - right_box[1])
    draw.text((margin - left_box[0], y - left_box[1]), left, font=label, fill=INK)
    draw.text(
        ((width - (mid_box[2] - mid_box[0])) / 2 - mid_box[0], y - mid_box[1]),
        mid,
        font=italic,
        fill=INK,
    )
    draw.text(
        (
            width - margin - (right_box[2] - right_box[0]) - right_box[0],
            y - right_box[1],
        ),
        right,
        font=label,
        fill=INK,
    )
    y += row_h + 12
    draw.rectangle([margin, y, width - margin, y + 2], fill=INK)
    return y + 2


def _draw_top5(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    y: int,
    width: int,
    teams: Sequence[Dict[str, Any]],
) -> None:
    margin = 48
    bottom = 630 - 48
    box_top = y + 24
    box_bottom = bottom
    box_left = margin
    box_right = width - margin
    border = 3
    draw.rectangle([box_left, box_top, box_right, box_bottom], outline=INK, width=border)
    inner_left = box_left + border
    inner_right = box_right - border
    inner_top = box_top + border
    inner_bottom = box_bottom - border
    cell_w = (inner_right - inner_left) / 5
    rank_font = _font("serif900", 36)
    name_font = _font("serif700", 22)
    for index, team in enumerate(teams[:5]):
        x0 = inner_left + index * cell_w
        x1 = x0 + cell_w
        if index > 0:
            draw.rectangle([int(x0) - 1, inner_top, int(x0) + 1, inner_bottom], fill=INK)
        cx = (x0 + x1) / 2
        rank = str(team.get("rank") or index + 1)
        _center_text(draw, rank, rank_font, cx, inner_top + 34, INK)
        logo = _load_logo(team.get("logo"), 64)
        image.paste(logo, (int(cx - 32), int(inner_top + 58)), logo)
        name = str(team.get("school") or "")
        # shrink until it fits the cell with padding
        size = 22
        font = name_font
        while size >= 14:
            font = _font("serif700", size)
            text_w, _ = _text_size(draw, name, font)
            if text_w <= cell_w - 16:
                break
            size -= 1
        _center_text(draw, name, font, cx, inner_bottom - 36, INK)


def render_og(
    *,
    season: int,
    week: int,
    postseason: bool,
    as_of: Optional[str],
    top_teams: Optional[Sequence[Dict[str, Any]]] = None,
) -> Image.Image:
    ensure_fonts()
    width, height = 1200, 630
    image = Image.new("RGB", (width, height), PAPER)
    draw = ImageDraw.Draw(image)

    if top_teams is None:
        week_label = "THE RANKINGS"
        edition = "Weekly Edition"
    elif postseason:
        week_label = "POSTSEASON"
        edition = "Postseason Edition"
    elif week <= 0:
        week_label = "PRESEASON"
        edition = "Preseason Edition"
    else:
        week_label = f"WEEK {week}"
        edition = f"Week {week} Edition"

    banner_h = _draw_banner(draw, width, height, week_label)
    mast = _font("mast", 118)
    _center_text(draw, "Bergstein", mast, width / 2, banner_h + 78, INK)
    y = _draw_dateline(draw, banner_h + 140, width, season, edition, format_updated(as_of))

    if top_teams:
        _draw_top5(image, draw, y, width, top_teams)
    else:
        italic = _font("italic", 34)
        _center_text(
            draw,
            "Power rankings, poll, and matchup picks",
            italic,
            width / 2,
            (y + height - 48) / 2,
            INK,
        )
    return image


def render_icon(size: int, *, maskable: bool = False, favicon: bool = False) -> Image.Image:
    ensure_fonts()
    image = Image.new("RGB", (size, size), PAPER)
    draw = ImageDraw.Draw(image)

    # Safe inset: maskable keeps content in the center 80% circle.
    inset = int(size * 0.10) if maskable else 0
    usable = size - 2 * inset
    band_h = max(1, int(usable * 0.16))
    draw.rectangle([inset, inset, size - inset, inset + band_h], fill=RED)

    thick = max(2, int(usable * 0.035))
    thin = max(1, int(usable * 0.012))
    rule_y = inset + band_h
    side = inset + int(usable * 0.12)
    draw.rectangle([side, rule_y, size - side, rule_y + thick], fill=INK)

    letter_size = int(usable * 0.55)
    font = _font("mast", letter_size)
    # optical center below the band/rule
    cx = size / 2
    cy = inset + band_h + (usable - band_h) * 0.48
    _center_text(draw, "B", font, cx, cy, INK)

    if not favicon:
        bottom_rule = inset + usable - int(usable * 0.14)
        draw.rectangle([side, bottom_rule, size - side, bottom_rule + thin], fill=INK)
    return image


def render_favicon_svg() -> str:
    """SVG favicon: red band, thick rule, B. No thin bottom rule."""
    ensure_fonts()
    # Embed the B outline from Old Standard so the favicon needs no web font.
    from fontTools.ttLib import TTFont
    from fontTools.pens.svgPathPen import SVGPathPen

    font = TTFont(FONTS_DIR / "OldStandard-Bold.ttf")
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap()
    name = cmap[ord("B")]
    pen = SVGPathPen(glyph_set)
    glyph_set[name].draw(pen)
    path = pen.getCommands()
    width = glyph_set[name].width
    upem = font["head"].unitsPerEm
    scale = 280 / upem
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="Bergstein">
  <rect width="512" height="512" fill="#F3EFE4"/>
  <rect x="0" y="0" width="512" height="82" fill="#B5121B"/>
  <rect x="72" y="82" width="368" height="18" fill="#161412"/>
  <g transform="translate(256 340) scale({scale:.6f} -{scale:.6f}) translate({-width/2:.1f} 0)">
    <path d="{path}" fill="#161412"/>
  </g>
</svg>
"""


def _write_ico(png_image: Image.Image, dest: Path) -> None:
    icon = png_image.resize((32, 32), Image.Resampling.LANCZOS)
    icon.save(dest, format="ICO", sizes=[(32, 32)])


def top5_from_power(power_path: Path, teams_path: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    power = json.loads(power_path.read_text(encoding="utf-8"))
    teams = {row["school"]: row for row in json.loads(teams_path.read_text(encoding="utf-8"))}
    rows = []
    for row in (power.get("rows") or [])[:5]:
        profile = teams.get(row["school"], {})
        rows.append(
            {
                "rank": row.get("rank"),
                "school": row.get("school"),
                "logo": profile.get("logo") or profile.get("logo_dark"),
            }
        )
    meta = {
        "season": int(power.get("season") or 2026),
        "week": int(power.get("week") or 0),
        "postseason": bool(power.get("postseason")),
        "as_of": power.get("as_of"),
        "label": power.get("label"),
    }
    return meta, rows


def generate_all(
    *,
    out_dir: Optional[Path] = None,
    power_path: Optional[Path] = None,
    teams_path: Optional[Path] = None,
) -> Dict[str, Path]:
    """Write OG images and icons. Returns a map of logical name → path."""
    ensure_fonts()
    out_dir = out_dir or WEB_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    power_path = power_path or (DOCS_DIR / "data" / "power.json")
    teams_path = teams_path or (DOCS_DIR / "data" / "teams.json")
    if not power_path.exists():
        power_path = PROJECT_ROOT / "docs" / "data" / "power.json"
    if not teams_path.exists():
        teams_path = PROJECT_ROOT / "docs" / "data" / "teams.json"

    written: Dict[str, Any] = {}

    default = render_og(season=2026, week=0, postseason=False, as_of=None, top_teams=None)
    default_path = out_dir / "og-default.png"
    default.save(default_path, "PNG", optimize=True)
    written["og-default"] = default_path

    weekly_name = "og-default.png"
    meta: Dict[str, Any] = {"season": 2026, "week": 0, "postseason": False, "as_of": None}
    if power_path.exists() and teams_path.exists():
        meta, top = top5_from_power(power_path, teams_path)
        weekly = render_og(
            season=meta["season"],
            week=meta["week"],
            postseason=meta["postseason"],
            as_of=meta["as_of"],
            top_teams=top,
        )
        weekly_name = week_slug(meta["season"], meta["week"], meta["postseason"])
        weekly_path = out_dir / weekly_name
        weekly.save(weekly_path, "PNG", optimize=True)
        written["og-weekly"] = weekly_path
    written["og_filename"] = weekly_name
    written["og_meta"] = meta

    icons = {
        "apple-touch-icon.png": render_icon(180),
        "icon-192.png": render_icon(192),
        "icon-512.png": render_icon(512),
        "icon-maskable-512.png": render_icon(512, maskable=True),
        "favicon-32.png": render_icon(32, favicon=True),
    }
    for name, image in icons.items():
        path = out_dir / name
        image.save(path, "PNG", optimize=True)
        written[name] = path

    favicon_svg = out_dir / "favicon.svg"
    favicon_svg.write_text(render_favicon_svg(), encoding="utf-8")
    written["favicon.svg"] = favicon_svg

    ico_path = out_dir / "favicon.ico"
    _write_ico(icons["favicon-32.png"], ico_path)
    written["favicon.ico"] = ico_path

    # Keep copies under static/ for older absolute paths during transition.
    static_dir = out_dir / "static"
    if static_dir.exists() or out_dir == WEB_DIR:
        static_dir.mkdir(parents=True, exist_ok=True)
        for name in (
            "apple-touch-icon.png",
            "icon-192.png",
            "icon-512.png",
            "icon-maskable-512.png",
            "favicon-32.png",
            "favicon.svg",
            "favicon.ico",
            "og-default.png",
        ):
            src = out_dir / name
            if src.exists():
                (static_dir / name).write_bytes(src.read_bytes())
        if "og-weekly" in written:
            weekly_src = written["og-weekly"]
            (static_dir / weekly_src.name).write_bytes(weekly_src.read_bytes())
            # Stable alias used by older meta tags
            (static_dir / "og-preview.png").write_bytes(weekly_src.read_bytes())

    return written


def apply_brand_meta(html: str, *, page: str, site: str, og_file: str, week: int) -> str:
    """Replace / inject Open Graph and icon tags for a published page."""
    page_url = {
        "power": f"{site}/power.html",
        "poll": f"{site}/poll.html",
        "matchup": f"{site}/",
    }.get(page, f"{site}/")
    title = {
        "power": "Bergstein College Football Rankings",
        "poll": "Bergstein College Football Rankings",
        "matchup": "Bergstein College Football Rankings",
    }[page if page in ("power", "poll", "matchup") else "power"]
    description = "Power rankings, poll, and matchup picks. Updated every week."
    alt = f"Bergstein Week {week} power rankings, top five teams" if week > 0 else "Bergstein college football rankings"
    image_url = f"{site}/{og_file}"

    block = f"""    <meta property="og:site_name" content="Bergstein" />
    <meta property="og:title" content="{title}" />
    <meta property="og:description" content="{description}" />
    <meta property="og:type" content="website" />
    <meta property="og:url" content="{page_url}" />
    <meta property="og:image" content="{image_url}" />
    <meta property="og:image:width" content="1200" />
    <meta property="og:image:height" content="630" />
    <meta property="og:image:alt" content="{alt}" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{title}" />
    <meta name="twitter:description" content="{description}" />
    <meta name="twitter:image" content="{image_url}" />
    <link rel="apple-touch-icon" href="./apple-touch-icon.png" />
    <link rel="icon" href="./favicon.svg" type="image/svg+xml" />
    <link rel="icon" href="./favicon.ico" sizes="32x32" />
    <link rel="manifest" href="./manifest.webmanifest" />
    <meta name="apple-mobile-web-app-title" content="Bergstein" />"""

    # Drop any prior og / twitter / icon / manifest tags so the block is clean.
    import re

    patterns = [
        r"\s*<meta property=\"og:[^\"]+\"[^>]*>",
        r"\s*<meta name=\"twitter:[^\"]+\"[^>]*>",
        r"\s*<link rel=\"apple-touch-icon\"[^>]*>",
        r"\s*<link rel=\"icon\"[^>]*>",
        r"\s*<link rel=\"manifest\"[^>]*>",
        r"\s*<meta name=\"apple-mobile-web-app-title\"[^>]*>",
    ]
    for pattern in patterns:
        html = re.sub(pattern, "", html)
    html = html.replace(
        '    <meta name="description"',
        block + '\n    <meta name="description"',
        1,
    )
    return html


def write_manifest(out_dir: Path) -> Path:
    payload = {
        "name": "Bergstein College Football",
        "short_name": "Bergstein",
        "description": "College football power rankings, poll, and matchups.",
        "start_url": "./index.html",
        "scope": "./",
        "display": "standalone",
        "background_color": "#F3EFE4",
        "theme_color": "#F3EFE4",
        "icons": [
            {
                "src": "./icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": "./icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": "./icon-maskable-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
            {
                "src": "./apple-touch-icon.png",
                "sizes": "180x180",
                "type": "image/png",
                "purpose": "any",
            },
        ],
    }
    path = out_dir / "manifest.webmanifest"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
