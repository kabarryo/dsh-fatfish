#!/usr/bin/env python3
"""Bundle the mascot frames into plugin/client.js.

Each sticker becomes ONE animated WebP (its original frame count, a per-state
frame duration and, for the scripted idle steps, an exact loop count), inlined
as a data URI: the client bundle loader serves a single JavaScript module and
no sibling asset files.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
FRAMES = ROOT / "assets" / "frames"
MANIFEST = ROOT / "assets" / "manifest.json"
TEMPLATE = ROOT / "src" / "client.template.js"
OUT = ROOT / "client.js"

SIZE = 192          # 2x of the 96px display size
QUALITY = 70
DURATION = {        # per-frame duration (ms) per state
    "waiting": 560,
    "typing": 560,
    "running": 220,
    "approval": 450,
    "question": 450,
    "error": 500,
    "done": 330,
    "idle": 1100,
    "stuffed": 720,
}


def animated(images: list[Image.Image], ms: int, loops: int) -> bytes:
    ims = [f.convert("RGBA") for f in images]
    if ims[0].width != SIZE:
        ims = [f.resize((SIZE, SIZE), Image.LANCZOS) for f in ims]
    buf = io.BytesIO()
    if len(ims) == 1:
        ims[0].save(buf, format="WEBP", quality=QUALITY, method=6)
    else:
        ims[0].save(buf, format="WEBP", save_all=True, append_images=ims[1:],
                    duration=ms, loop=loops, quality=QUALITY, method=6, allow_mixed=True)
    return buf.getvalue()


def sticker(item: dict, ms: int, loops: int) -> dict:
    sid = item["id"]
    files = sorted(FRAMES.joinpath(item["dir"]).glob(f"{sid}-*.webp"))
    ims = [Image.open(f) for f in files]
    data = animated(ims, ms, loops)
    return {
        "id": sid,
        "label": item["label"],
        "src": "data:image/webp;base64," + base64.b64encode(data).decode("ascii"),
        "ms": ms,
        "count": len(files),
        "loops": loops,
    }


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    total = 0

    pools: dict[str, list[dict]] = {}
    for state, items in manifest["pools"].items():
        ms = DURATION.get(state, 500)
        pools[state] = [sticker(item, ms, 0) for item in items]
        total += len(pools[state])
        print(f"{state:9s} {len(pools[state])} stickers")

    idle_src = manifest["idle"]
    idle_ms = DURATION["idle"]
    idle = {
        "afterMs": idle_src["afterMs"],
        "opening": [sticker(item, idle_ms, 0) for item in idle_src["opening"]],
        "sequence": [sticker(item, idle_ms, item.get("loops", 0)) for item in idle_src["sequence"]],
    }
    total += len(idle["opening"]) + len(idle["sequence"])
    print("idle      opening %d + sequence %d" % (len(idle["opening"]), len(idle["sequence"])))

    data = {"pools": pools, "idle": idle}
    template = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(template.replace("/*__FRAMES__*/", payload), encoding="utf-8")
    print(f"client.js {OUT.stat().st_size / 1024:.0f} KB ({total} stickers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
