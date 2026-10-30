#!/usr/bin/env python3
"""Build transparent mascot frames for the demo (diwer/ai-biaoqingbao pack).

Eight states own a *pool* of stickers (one is picked at random on entry). The
idle state is scripted instead: one of two opening stickers, then a fixed
sequence after IDLE_AFTER_MS, ending locked on the charging sticker.

Every sticker keeps its ORIGINAL frame count (2-4 frames, no resampling).

Per sticker:
  1. flood-fill the border-connected background (sampled from the corners, so a
     light-gray backdrop works as well as white) to alpha 0, feather 1px
  2. crop the baked-in caption band
  3. fit the content bbox into the canvas (a per-sticker `scale` overrides it)
  4. write WebP frames at 2x display size + a review sheet
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "assets" / "raw" / "diwer"
OUT = ROOT / "assets" / "frames"
REVIEW = ROOT / "docs"

SIZE = 192           # 2x of the 96px display size
CAPTION_CROP = 0.78  # keep the top 78%, dropping the caption band
FIT = 0.94           # content fills this share of the canvas
BG_TOL = 26          # per-channel tolerance when flood-filling the backdrop

# state -> sticker ids, random pick per entry
POOLS: dict[str, list[str]] = {
    "waiting": ["081", "019"],
    "typing": ["009", "020", "022"],
    "running": ["074", "075", "065", "076"],
    "approval": ["034", "028", "021"],
    "question": ["033", "049", "093"],
    "error": ["037", "036", "069"],
    "done": ["094", "003", "091", "047"],
    "stuffed": ["088", "072"],
}

# 闲置是脚本，不是池子
IDLE_AFTER_MS = 120000
IDLE_OPENING = ["064", "044"]
IDLE_SEQUENCE = [("007", 3), ("018", 2), ("073", 0)]  # (sticker, loops)；0 = 锁定

SCALE = {"065": 0.94, "070": 0.94, "075": 0.94, "080": 0.94, "069": 0.94}
LABELS = {
    "081": "期待", "019": "在吗",
    "009": "收到！", "020": "来了", "022": "马上到",
    "074": "干饭人", "075": "先吃一口", "065": "赶工中", "070": "CPU烧了", "076": "咖啡续命",
    "080": "紧张", "034": "啊这", "021": "等一下", "028": "拜托了",
    "078": "疑惑", "049": "尊嘟假嘟", "093": "确认眼神", "033": "真的假的",
    "037": "麻了", "038": "破防了", "069": "我太难了", "036": "我裂开了",
    "094": "恭喜", "003": "点赞", "084": "得意", "047": "拿捏了", "091": "满血复活",
    "064": "摸鱼中", "044": "不想说话", "007": "困了", "018": "晚安", "073": "充电中",
    "088": "撑了", "072": "让我缓缓",
}


def bg_color(img: Image.Image) -> tuple[int, int, int]:
    arr = np.array(img.convert("RGB"))
    corners = [arr[0, 0], arr[0, -1], arr[-1, 0], arr[-1, -1]]
    return tuple(int(np.median([c[i] for c in corners])) for i in range(3))  # type: ignore[return-value]


def cut_background(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    arr = np.array(rgba)
    rgb = arr[:, :, :3].astype(np.int16)
    bg = np.array(bg_color(img), dtype=np.int16)
    near_bg = (np.abs(rgb - bg).max(axis=2) <= BG_TOL)

    h, w = near_bg.shape
    seen = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    for x in range(w):
        for y in (0, h - 1):
            if near_bg[y, x] and not seen[y, x]:
                seen[y, x] = True
                q.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if near_bg[y, x] and not seen[y, x]:
                seen[y, x] = True
                q.append((y, x))
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not seen[ny, nx] and near_bg[ny, nx]:
                seen[ny, nx] = True
                q.append((ny, nx))

    alpha = np.where(seen, 0, 255).astype(np.uint8)
    alpha_img = Image.fromarray(alpha, "L").filter(ImageFilter.GaussianBlur(0.8))
    alpha_img = alpha_img.point(lambda v: 0 if v < 48 else 255 if v > 208 else v)
    arr[:, :, 3] = np.array(alpha_img)
    return Image.fromarray(arr, "RGBA")


def sticker_frames(sid: str) -> list[Image.Image]:
    src = RAW / f"{sid}.webp"
    im = Image.open(src)
    frames = []
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        frame = cut_background(im.copy())
        w, h = frame.size
        frames.append(frame.crop((0, 0, w, int(h * CAPTION_CROP))))
    return frames


def composite(frames: list[Image.Image], scale: float) -> list[Image.Image]:
    box = [f.getbbox() for f in frames]
    left = min(b[0] for b in box)
    top = min(b[1] for b in box)
    right = max(b[2] for b in box)
    bottom = max(b[3] for b in box)
    cw, ch = right - left, bottom - top
    factor = (SIZE * FIT / max(cw, ch)) * scale
    out = []
    for frame in frames:
        crop = frame.crop((left, top, right, bottom))
        w, h = round(cw * factor), round(ch * factor)
        crop = crop.resize((max(1, w), max(1, h)), Image.LANCZOS)
        canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        # 底部对齐：所有表情的脚都落在同一条基线上，贴住输入框上沿，
        # 否则宽构图（端碗、坐桌前）的表情会在画布里居中而“浮”起来。
        canvas.alpha_composite(crop, ((SIZE - w) // 2, SIZE - h))
        out.append(canvas)
    return out


def build(group: str, ids: list[str], built: dict[str, dict], strips: list[Image.Image]) -> list[dict]:
    dest = OUT / group
    dest.mkdir(parents=True, exist_ok=True)
    items = []
    for sid in ids:
        frames = composite(sticker_frames(sid), SCALE.get(sid, 1.0))
        for i, frame in enumerate(frames):
            frame.save(dest / f"{sid}-{i}.webp", "WEBP", quality=90, method=6)
        item = {"id": sid, "label": LABELS.get(sid, sid), "frames": len(frames), "dir": group}
        items.append(item)
        built[sid] = item
        print(f"{group:9s} {sid} {item['label']} frames={len(frames)}")
        strip = Image.new("RGBA", (len(frames) * (SIZE + 6), SIZE), (0, 0, 0, 0))
        for i, frame in enumerate(frames):
            strip.alpha_composite(frame, (i * (SIZE + 6), 0))
        strips.append(strip)
    return items


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    REVIEW.mkdir(parents=True, exist_ok=True)
    for stale in OUT.rglob("*.webp"):
        stale.unlink()

    built: dict[str, dict] = {}
    strips: list[Image.Image] = []
    pools = {state: build(state, ids, built, strips) for state, ids in POOLS.items()}
    build("idle", IDLE_OPENING + [sid for sid, _ in IDLE_SEQUENCE], built, strips)

    idle = {
        "afterMs": IDLE_AFTER_MS,
        "opening": [built[sid] for sid in IDLE_OPENING],
        "sequence": [dict(built[sid], loops=loops) for sid, loops in IDLE_SEQUENCE],
    }
    manifest = {"pools": pools, "idle": idle}
    canonical = ROOT / "assets" / "manifest.json"
    canonical.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    preview = ROOT / "demo" / "manifest.js"
    preview.write_text("window.__MASCOT__ = " + json.dumps(manifest, ensure_ascii=False, indent=1) + ";\n",
                       encoding="utf-8")
    print("manifest ->", canonical)

    width = max(r.width for r in strips)
    for label, bg in (("light", (250, 250, 250, 255)), ("dark", (26, 27, 31, 255))):
        sheet = Image.new("RGBA", (width, len(strips) * (SIZE + 4)), bg)
        y = 0
        for row in strips:
            sheet.alpha_composite(row, (0, y))
            y += SIZE + 4
        sheet.convert("RGB").save(REVIEW / f"frames-{label}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
