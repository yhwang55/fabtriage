"""Wafer maps: render a measured wafer as an image, then find its thick regions.

The image shows each point's deviation from the wafer's own mean, so it shows shape
(center-thick, edge ring, a local spot), not the overall offset. Regions more than
THICK_DELTA above the wafer mean are painted red.

Segmentation runs on SAM 3.1 through the Meta Model API when WAFERMAP_SEGMENTER=sam
(the default when a key is set), and on a local connected-component pass otherwise or if
the SAM call fails. Both return the same summary.
"""

from __future__ import annotations

import base64
import math
import os
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from .sim import SITES

SIZE = 256
THICK_DELTA = 3.0
SAM_PROMPT = "red region"
_BOX = re.compile(r"(\d+)<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)\|>")


def _grid(sites: list) -> tuple:
    """Inverse-distance interpolation of 49 site values onto the wafer disk."""
    values = np.array(sites) - float(np.mean(sites))
    lin = np.linspace(-1, 1, SIZE)
    xx, yy = np.meshgrid(lin, -lin)
    inside = xx**2 + yy**2 <= 1.0
    d2 = (xx[..., None] - SITES[:, 0]) ** 2 + (yy[..., None] - SITES[:, 1]) ** 2
    w = 1.0 / (d2 + 1e-3) ** 1.5
    field = (w * values).sum(-1) / w.sum(-1)
    field = ndimage.gaussian_filter(field, sigma=4)
    return field, inside, xx, yy


def render(sites: list, path: Path) -> Path:
    field, inside, _, _ = _grid(sites)
    img = np.full((SIZE, SIZE, 3), 255, dtype=np.uint8)
    shade = np.clip(128 + field * 12, 40, 215).astype(np.uint8)
    img[inside] = np.stack([shade[inside] * 0.55, shade[inside] * 0.65, shade[inside]], -1).astype(np.uint8)
    hot = inside & (field > THICK_DELTA)
    img[hot] = (220, 30, 30)
    im = Image.fromarray(img)
    ImageDraw.Draw(im).ellipse([0, 0, SIZE - 1, SIZE - 1], outline=(60, 60, 60), width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


def _describe(r: float, area_frac: float, r_max: float, ang_span: float, r_min: float = 1.0) -> str:
    """r is the region's mean distance from the wafer center (0 center, 1 edge)."""
    if area_frac > 0.6:
        return "most_of_wafer"
    if (r < 0.4 or r_min < 0.1) and area_frac > 0.04:
        return "center"
    if r_max > 0.85 and ang_span > 180:
        return "edge_ring"
    if r_max > 0.85:
        return "edge_arc"
    return "local_spot"


def segment_local(sites: list) -> list:
    field, inside, xx, yy = _grid(sites)
    hot = inside & (field > THICK_DELTA)
    labels, n = ndimage.label(hot)
    regions = []
    total = inside.sum()
    edge_cover = np.zeros(36, dtype=bool)
    for k in range(1, n + 1):
        m = labels == k
        if m.sum() < 30:
            continue
        rr = np.hypot(xx[m], yy[m])
        ang = np.degrees(np.arctan2(yy[m], xx[m]))
        hist = np.histogram(ang, bins=36, range=(-180, 180))[0] > 0
        loc = _describe(float(rr.mean()), m.sum() / total, float(rr.max()), 10.0 * hist.sum(), float(rr.min()))
        if loc.startswith("edge"):
            edge_cover |= hist
        regions.append(
            {
                "location": loc,
                "area_pct": round(100 * float(m.sum() / total), 1),
                "peak_above_mean_A": round(float(field[m].max()), 2),
            }
        )
    # several thick arcs that together go most of the way around the edge are one ring
    if len(regions) > 1 and all(r["location"].startswith("edge") for r in regions) and (edge_cover.sum() >= 18 or (len(regions) >= 3 and edge_cover.sum() >= 10)):
        regions = [
            {
                "location": "edge_ring",
                "area_pct": round(sum(r["area_pct"] for r in regions), 1),
                "peak_above_mean_A": max(r["peak_above_mean_A"] for r in regions),
                "arcs": len(regions),
            }
        ]
    return regions


def segment_sam(client, image: Path) -> list:
    data = "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode()
    response = client.responses.create(
        model=os.environ.get("SAM_MODEL") or "sam-3.1",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": SAM_PROMPT},
                    {"type": "input_image", "image_url": data},
                ],
            }
        ],
    )
    regions = []
    for match in _BOX.finditer(response.output_text or ""):
        _, x1, y1, x2, y2, w, h = (int(v) for v in match.groups())
        # boxes come back in the image's pixel space (w, h are the image size)
        cx = ((x1 + x2) / 2) / w * 2 - 1
        cy = 1 - ((y1 + y2) / 2) / h * 2
        bw, bh = (x2 - x1) / w * 2, (y2 - y1) / h * 2
        area = (bw * bh) / math.pi
        corners = [math.hypot(px, py) for px in (cx - bw / 2, cx + bw / 2) for py in (cy - bh / 2, cy + bh / 2)]
        wide = bw > 1.6 and bh > 1.6
        regions.append(
            {
                "location": "wafer_wide" if wide else _describe(math.hypot(cx, cy), min(area, 1.0), min(max(corners), 1.0), 90, math.hypot(cx, cy)),
                "area_pct": round(100 * min(area, 1.0), 1),
            }
        )
    return regions


def summarize(sites: list, image: Path, client=None) -> dict:
    mode = os.environ.get("WAFERMAP_SEGMENTER", "sam" if client is not None else "local")
    regions, used, note = None, "local", None
    if mode == "sam" and client is not None:
        try:
            regions, used = segment_sam(client, image), "sam-3.1"
        except Exception as error:  # fall back so one failed call doesn't end the run
            note = f"SAM call failed ({type(error).__name__}); used local segmentation"
    if regions is None:
        regions = segment_local(sites)
    out = {
        "segmenter": used,
        "thick_regions": regions,
        "pattern": regions[0]["location"] if len(regions) == 1 else ("none" if not regions else "multiple"),
        "within_wafer_range_A": round(float(max(sites) - min(sites)), 2),
        "image": f"maps/{image.name}",
    }
    if note:
        out["note"] = note
    return out

