#!/usr/bin/env python3
import os
import sys
import re
import json
import shutil
import urllib.request
from typing import Any, Dict, List, Tuple, Optional

"""
restore_assets_py.py

用途：
- 还原 Cocos Creator 项目的资源到独立输出目录，包含音频、图集（plist+纹理）、
  自动推断的序列动画，以及从导入 JSON 中解析的 cc.AnimationClip。

参数要求：
- 第一个参数必须是资源根目录，并且该目录下必须存在 'import' 与 'native' 两个子目录。
- 第二个参数为输出目录，脚本会创建并写入：
  - audio/
  - spine/
  - sprite_atlases/
  - animations/
  - animations_auto/

用法示例：
- python3 restore_assets_py.py /path/to/assets/resources /path/to/output

说明：
- 从 '<assets_resources_root>/import' 读取 JSON 并解析动画、图集帧数据；
- 从 '<assets_resources_root>/native' 复制图片与音频资源；
- 若输入目录不包含 'import' 与 'native'，脚本会报错并退出。
"""


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def safe_slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "_", str(s))


def walk_files(root: str, exts: Tuple[str, ...]) -> List[str]:
    out: List[str] = []
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            if f.lower().endswith(exts):
                out.append(os.path.join(dirpath, f))
    return out


def read_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def extract_audio(native_root: str, out_root: str) -> Dict[str, str]:
    audio_out = os.path.join(out_root, "audio")
    ensure_dir(audio_out)
    audio_map: Dict[str, str] = {}
    for path in walk_files(native_root, (".mp3", ".ogg", ".wav", ".m4a")):
        base = os.path.basename(path)
        name = safe_slug(os.path.splitext(base)[0])
        ext = os.path.splitext(base)[1].lower()
        target = os.path.join(audio_out, f"{name}{ext}")
        i = 1
        while os.path.exists(target):
            target = os.path.join(audio_out, f"{name}_{i}{ext}")
            i += 1
        shutil.copy2(path, target)
        audio_map[path] = target
    return audio_map


# ------------ Image size readers (PNG/WEBP) ------------
def read_png_size(file_path: str) -> Optional[Dict[str, int]]:
    try:
        with open(file_path, "rb") as fh:
            buf = fh.read(32)
        if len(buf) < 24:
            return None
        if buf[1:4].decode("ascii", errors="ignore") != "PNG":
            return None
        w = int.from_bytes(buf[16:20], "big")
        h = int.from_bytes(buf[20:24], "big")
        return {"width": w, "height": h}
    except Exception:
        return None

def read_jpeg_size(file_path: str) -> Optional[Dict[str, int]]:
    try:
        with open(file_path, "rb") as fh:
            data = fh.read()
        # JPEG starts with 0xFFD8
        if len(data) < 4 or data[0] != 0xFF or data[1] != 0xD8:
            return None
        off = 2
        # Iterate segments until SOF0/1/2
        while off + 3 < len(data):
            if data[off] != 0xFF:
                # skip stray bytes
                off += 1
                continue
            marker = data[off + 1]
            # Standalone markers without length
            if marker in (0xD8, 0xD9):
                off += 2
                continue
            if off + 4 > len(data):
                break
            seg_len = (data[off + 2] << 8) | data[off + 3]
            if seg_len < 2 or off + 2 + seg_len > len(data):
                break
            if marker in (0xC0, 0xC1, 0xC2):  # SOF0/1/2
                if seg_len >= 7:
                    # [precision][height][width]...
                    height = (data[off + 5] << 8) | data[off + 6]
                    width = (data[off + 7] << 8) | data[off + 8]
                    return {"width": width, "height": height}
                else:
                    return None
            off += 2 + seg_len
        return None
    except Exception:
        return None


def read_webp_size(file_path: str) -> Optional[Dict[str, int]]:
    try:
        with open(file_path, "rb") as fh:
            buf = fh.read()
        if len(buf) < 12:
            return None
        if buf[0:4] != b"RIFF" or buf[8:12] != b"WEBP":
            return None
        off = 12
        while off + 8 <= len(buf):
            chunk = buf[off:off + 4]
            size = int.from_bytes(buf[off + 4:off + 8], "little")
            data_start = off + 8
            if chunk == b"VP8X":
                w_minus_1 = int.from_bytes(buf[data_start + 4:data_start + 7], "little")
                h_minus_1 = int.from_bytes(buf[data_start + 7:data_start + 10], "little")
                return {"width": w_minus_1 + 1, "height": h_minus_1 + 1}
            elif chunk == b"VP8 " and size >= 10:
                sig_off = data_start + 3
                if buf[sig_off:sig_off + 3] == b"\x9d\x01\x2a":
                    w = int.from_bytes(buf[sig_off + 3:sig_off + 5], "little") & 0x3FFF
                    h = int.from_bytes(buf[sig_off + 5:sig_off + 7], "little") & 0x3FFF
                    return {"width": w, "height": h}
            elif chunk == b"VP8L" and size >= 5:
                if buf[data_start] == 0x2F:
                    b1 = buf[data_start + 1]
                    b2 = buf[data_start + 2]
                    b3 = buf[data_start + 3]
                    b4 = buf[data_start + 4]
                    width = (b1 | ((b2 & 0x3F) << 8)) + 1
                    height = ((b2 >> 6) | (b3 << 2) | ((b4 & 0x03) << 10)) + 1
                    return {"width": width, "height": height}
            off = data_start + ((size + 1) & ~1)
        return None
    except Exception:
        return None


def get_image_size(file_path: str) -> Optional[Dict[str, int]]:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".png":
        return read_png_size(file_path)
    if ext == ".webp":
        return read_webp_size(file_path)
    if ext in (".jpg", ".jpeg"):
        return read_jpeg_size(file_path)
    return None

def is_image_magic_ok(file_path: str) -> bool:
    try:
        with open(file_path, "rb") as fh:
            head = fh.read(12)
        if len(head) < 4:
            return False
        # PNG
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return True
        # JPEG
        if head[:2] == b"\xff\xd8":
            return True
        # WEBP (RIFF....WEBP)
        if head[:4] == b"RIFF":
            # read more to check WEBP tag
            with open(file_path, "rb") as fh:
                buf = fh.read(16)
            if len(buf) >= 12 and buf[8:12] == b"WEBP":
                return True
        return False
    except Exception:
        return False

def extract_stub_url(file_path: str) -> Optional[str]:
    try:
        with open(file_path, "rb") as fh:
            data = fh.read(1024)
        s = data.decode("utf-8", errors="ignore")
        if "No Content" not in s:
            return None
        m = re.search(r"(https?://[^\s%]+)", s)
        if m:
            return m.group(1)
        return None
    except Exception:
        return None

def copy_image_resolving_stub(src: str, dst: str) -> bool:
    # If src is a real image, copy directly
    if is_image_magic_ok(src):
        try:
            shutil.copy2(src, dst)
            return True
        except Exception:
            return False
    # Try to resolve stub URL
    url = extract_stub_url(src)
    if url:
        try:
            with urllib.request.urlopen(url) as resp:
                content = resp.read()
            with open(dst, "wb") as fh:
                fh.write(content)
            return True
        except Exception:
            return False
    # Fallback: attempt raw copy anyway
    try:
        shutil.copy2(src, dst)
        return True
    except Exception:
        return False


# ------------ Animation clip parsing ------------
def parse_animation_clip(data: Any) -> List[Dict[str, Any]]:
    clips: List[Dict[str, Any]] = []
    uuids: List[str] = []
    if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
        uuids = [u for u in data[1] if isinstance(u, str)]

    def find_clips(node: Any, current: Optional[Dict[str, Any]] = None):
        if isinstance(node, list):
            if (
                len(node) >= 3
                and isinstance(node[0], (int, float))
                and isinstance(node[1], str)
                and isinstance(node[2], (int, float))
                and (len(node) < 4 or isinstance(node[3], (int, float)))
            ):
                current = {
                    "name": node[1],
                    "duration": float(node[2]),
                    "sample": float(node[3]) if len(node) > 3 and isinstance(node[3], (int, float)) else None,
                    "tracks": [],
                }
                clips.append(current)

            if any(isinstance(x, str) and x == "spriteFrame" for x in node):
                def collect_frames(n: Any) -> List[Dict[str, Any]]:
                    frames: List[Dict[str, Any]] = []
                    if isinstance(n, list):
                        for entry in n:
                            if (
                                isinstance(entry, list)
                                and len(entry) >= 4
                                and isinstance(entry[0], dict)
                                and "frame" in entry[0]
                                and any(x == "value" for x in entry)
                            ):
                                t = float(entry[0]["frame"]) if isinstance(entry[0]["frame"], (int, float)) else None
                                idx = None
                                for i in range(1, len(entry)):
                                    if entry[i] == 6 and i + 1 < len(entry) and isinstance(entry[i + 1], int):
                                        idx = entry[i + 1]
                                        break
                                uuid = uuids[idx] if (idx is not None and 0 <= idx < len(uuids)) else None
                                frames.append({"time": t, "uuid": uuid, "uuid_index": idx})
                        for entry in n:
                            frames.extend(collect_frames(entry))
                    return frames

                frames = collect_frames(node)
                if current is not None and frames:
                    current["tracks"].append({"type": "spriteFrame", "frames": frames})

            for child in node:
                find_clips(child, current)

    find_clips(data, None)
    return clips


def extract_animations(import_root: str, out_root: str) -> List[Dict[str, Any]]:
    anim_out = os.path.join(out_root, "animations")
    ensure_dir(anim_out)
    collected: List[Dict[str, Any]] = []
    for path in walk_files(import_root, (".json",)):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                txt = fh.read()
            if "cc.AnimationClip" not in txt:
                continue
            data = json.loads(txt)
        except Exception:
            continue
        clips = parse_animation_clip(data)
        if not clips:
            continue
        for clip in clips:
            name = safe_slug(clip.get("name") or os.path.splitext(os.path.basename(path))[0])
            out_file = os.path.join(anim_out, f"{name}.anim.json")
            with open(out_file, "w", encoding="utf-8") as fh:
                json.dump(clip, fh, ensure_ascii=False, indent=2)
            collected.append({"name": clip.get("name"), "path": out_file})
    index_path = os.path.join(anim_out, "index.json")
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump({"clips": collected}, fh, ensure_ascii=False, indent=2)
    return collected


# ------------ Spine & SpriteFrames extraction ------------
def walk(node: Any, visitor):
    if isinstance(node, list):
        visitor(node)
        for v in node:
            walk(v, visitor)
    elif isinstance(node, dict):
        visitor(node)
        for k in list(node.keys()):
            walk(node[k], visitor)


def extract_skeleton_entries(json_data: Any) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    def visit(node: Any):
        if (
            isinstance(node, list)
            and len(node) >= 6
            and node[0] == 0
            and isinstance(node[1], str)
            and isinstance(node[2], str)
            and isinstance(node[3], list)
            and isinstance(node[4], dict)
            and isinstance(node[5], list)
        ):
            entries.append({
                "name": node[1],
                "atlasText": node[2],
                "skeletonJson": node[4],
                "textureNames": node[3],
                "textureIndices": node[5],
            })
    walk(json_data, visit)
    return entries


def extract_sprite_frames(json_data: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    def visit(node: Any):
        if isinstance(node, dict) and node.get("name") and node.get("rect") and node.get("originalSize"):
            out.append({
                "name": node.get("name"),
                "rotated": bool(node.get("rotated", False)),
                "rect": node.get("rect"),
                "offset": node.get("offset", [0, 0]),
                "originalSize": node.get("originalSize"),
            })
    walk(json_data, visit)
    return out


def guess_texture_uuid_compressed(json_data: Any) -> Optional[str]:
    if isinstance(json_data, list) and len(json_data) > 1 and isinstance(json_data[1], list) and json_data[1] and isinstance(json_data[1][0], str):
        return json_data[1][0]
    return None


def to_plist_string(obj: Any, indent: str = "") -> str:
    if obj is None:
        return f"{indent}<null/>\n"
    if isinstance(obj, str):
        return f"{indent}<string>{obj}</string>\n"
    if isinstance(obj, bool):
        return f"{indent}<{ 'true' if obj else 'false' }/>\n"
    if isinstance(obj, (int, float)):
        return f"{indent}<integer>{int(obj)}</integer>\n"
    if isinstance(obj, list):
        s = f"{indent}<array>\n"
        for v in obj:
            s += to_plist_string(v, indent + "  ")
        s += f"{indent}</array>\n"
        return s
    if isinstance(obj, dict):
        s = f"{indent}<dict>\n"
        for k in obj.keys():
            s += f"{indent}  <key>{k}</key>\n"
            s += to_plist_string(obj[k], indent + "  ")
        s += f"{indent}</dict>\n"
        return s
    return f"{indent}<string>{str(obj)}</string>\n"


def build_plist(frames: Dict[str, Dict[str, Any]], texture_file_name: str) -> str:
    plist_obj = {
        "frames": frames,
        "metadata": {
            "format": 2,
            "textureFileName": texture_file_name,
        },
    }
    xml = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
    xml += "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
    xml += "<plist version=\"1.0\">\n"
    xml += to_plist_string(plist_obj)
    xml += "</plist>\n"
    return xml


def parse_rect(rect: Any) -> Dict[str, int]:
    if not isinstance(rect, list):
        return {"x": 0, "y": 0, "w": 0, "h": 0}
    if rect and isinstance(rect[0], list):
        return {"x": int(rect[0][0]), "y": int(rect[0][1]), "w": int(rect[1][0]), "h": int(rect[1][1])}
    return {"x": int(rect[0]), "y": int(rect[1]), "w": int(rect[2]), "h": int(rect[3])}


def parse_pair(pair: Any) -> Dict[str, int]:
    if not isinstance(pair, list):
        return {"x": 0, "y": 0}
    return {"x": int(pair[0]), "y": int(pair[1])}


def main():
    if len(sys.argv) < 3:
        print("用法: restore_assets_py.py <assets_resources_root> <output_dir>")
        sys.exit(1)

    assets_root = sys.argv[1]
    output_dir = sys.argv[2]

    import_root = os.path.join(assets_root, "import")
    native_root = os.path.join(assets_root, "native")

    # 严格要求存在 import/native 子目录，否则报错退出
    if not (os.path.isdir(import_root) and os.path.isdir(native_root)):
        print(f"[错误] 资源根目录必须包含 'import' 与 'native' 子目录: {assets_root}", file=sys.stderr)
        print("用法: restore_assets_py.py <assets_resources_root> <output_dir>", file=sys.stderr)
        sys.exit(1)

    bucket_tag: Optional[str] = None

    ensure_dir(output_dir)
    out_spine = os.path.join(output_dir, "spine")
    out_atlas = os.path.join(output_dir, "sprite_atlases")
    ensure_dir(out_spine)
    ensure_dir(out_atlas)

    # 1) Audio
    print("[1/3] Extracting audio...")
    audio_map = extract_audio(native_root, output_dir)
    print(f"Extracted {len(audio_map)} audio files to {os.path.join(output_dir, 'audio')}")

    # Cache native images by two-char prefix
    native_images = [p for p in walk_files(native_root, (".png", ".webp", ".jpg", ".jpeg"))]
    native_by_prefix: Dict[str, List[str]] = {}
    for f in native_images:
        rel = os.path.relpath(f, native_root)
        first = rel.split(os.sep)[0]
        # 正常情况下 first 是两位十六进制的桶前缀；否则使用 bucket_tag 作为归类前缀
        if re.match(r"^[0-9a-fA-F]{2}$", first):
            prefix = first.lower()
        elif bucket_tag:
            prefix = bucket_tag
        else:
            prefix = "__misc__"
        native_by_prefix.setdefault(prefix, []).append(f)

    # 2) Restore Spine & collect SpriteFrames
    print("[2/3] Restoring Spine and collecting SpriteFrames...")
    atlas_groups: Dict[str, Dict[str, Any]] = {}
    for jf in walk_files(import_root, (".json",)):
        json_data = read_json(jf)
        if json_data is None:
            continue

        # Spine
        skeletons = extract_skeleton_entries(json_data)
        if skeletons:
            uuids: List[str] = json_data[1] if (isinstance(json_data, list) and len(json_data) > 1 and isinstance(json_data[1], list)) else []
            for sk in skeletons:
                dir_name = safe_slug(sk["name"]) if sk.get("name") else "spine"
                spine_dir = os.path.join(out_spine, dir_name)
                ensure_dir(spine_dir)
                with open(os.path.join(spine_dir, f"{dir_name}.atlas"), "w", encoding="utf-8") as fh:
                    fh.write(sk["atlasText"])
                with open(os.path.join(spine_dir, f"{dir_name}.json"), "w", encoding="utf-8") as fh:
                    json.dump(sk["skeletonJson"], fh, ensure_ascii=False, indent=2)

                target_image: Optional[str] = None
                m = re.search(r"size:\s*(\d+)\s*,\s*(\d+)", sk["atlasText"], re.IGNORECASE)
                if uuids:
                    idx = 0
                    if isinstance(sk.get("textureIndices"), list) and sk["textureIndices"] and isinstance(sk["textureIndices"][0], int):
                        idx = sk["textureIndices"][0]
                    comp_uuid = uuids[idx] if 0 <= idx < len(uuids) else uuids[0]
                    prefix = comp_uuid[:2]
                    cand = native_by_prefix.get(prefix, [])
                    if not cand and bucket_tag:
                        cand = native_by_prefix.get(bucket_tag, [])
                    if m:
                        W = int(m.group(1))
                        H = int(m.group(2))
                        for f in cand:
                            sz = get_image_size(f)
                            if sz and sz.get("width") == W and sz.get("height") == H:
                                target_image = f
                                break
                    if not target_image and cand:
                        target_image = cand[0]
                if target_image:
                    ext = os.path.splitext(target_image)[1].lower()
                    if isinstance(sk.get("textureNames"), list) and sk["textureNames"] and isinstance(sk["textureNames"][0], str):
                        # 保留原名称，但调整扩展名与源文件一致，避免内容与扩展不匹配
                        name_no_ext, _ = os.path.splitext(sk["textureNames"][0])
                        base_name = name_no_ext + ext
                    else:
                        base_name = f"texture{ext}"
                    copy_image_resolving_stub(target_image, os.path.join(spine_dir, base_name))

        # SpriteFrames
        tex_uuid_comp = guess_texture_uuid_compressed(json_data)
        frames = extract_sprite_frames(json_data)
        if tex_uuid_comp and frames:
            grp = atlas_groups.setdefault(tex_uuid_comp, {"frames": {}, "sources": set()})
            grp["sources"].add(os.path.basename(jf))
            for fr in frames:
                name = fr["name"]
                if name not in grp["frames"]:
                    grp["frames"][name] = fr

    # 3) Emit plist atlases
    print("[3/3] Emitting plist atlases...")
    for comp_uuid, group in atlas_groups.items():
        prefix = comp_uuid[:2]
        cand = native_by_prefix.get(prefix, [])
        if not cand and bucket_tag:
            cand = native_by_prefix.get(bucket_tag, [])
        image_file = None
        # Prefer locally valid image bytes
        for ext in ('.png', '.webp', '.jpg', '.jpeg'):
            for f in cand:
                if f.lower().endswith(ext) and is_image_magic_ok(f):
                    image_file = f
                    break
            if image_file:
                break
        # If none valid locally, fall back to first by extension (may be stub; we'll attempt URL download at copy time)
        if image_file is None:
            for ext in ('.png', '.webp', '.jpg', '.jpeg'):
                for f in cand:
                    if f.lower().endswith(ext):
                        image_file = f
                        break
                if image_file:
                    break
        texture_file_name = os.path.basename(image_file) if image_file else f"texture_{prefix}.png"
        frames_obj: Dict[str, Dict[str, Any]] = {}
        for name, fr in group["frames"].items():
            r = parse_rect(fr["rect"])
            off = parse_pair(fr.get("offset", [0, 0]))
            osz = parse_pair(fr.get("originalSize", [r["w"], r["h"]]))
            frames_obj[name] = {
                "rotated": bool(fr.get("rotated", False)),
                "frame": f"{{{r['x']},{r['y']}}},{{{r['w']},{r['h']}}}",
                "offset": f"{{{off['x']},{off['y']}}}",
                "sourceSize": f"{{{osz['x']},{osz['y']}}}",
            }
        plist_xml = build_plist(frames_obj, texture_file_name)
        out_dir = os.path.join(out_atlas, prefix + '_' + safe_slug(comp_uuid[:6]))
        ensure_dir(out_dir)
        plist_name = 'atlas_' + safe_slug(comp_uuid[:8]) + '.plist'
        with open(os.path.join(out_dir, plist_name), "w", encoding="utf-8") as fh:
            fh.write(plist_xml)
        # 清理旧的纹理文件，避免残留不可用的占位图片造成困扰
        try:
            for old in os.listdir(out_dir):
                if old.lower().endswith(('.png', '.webp', '.jpg', '.jpeg')) and old != texture_file_name:
                    try:
                        os.remove(os.path.join(out_dir, old))
                    except Exception:
                        pass
        except Exception:
            pass
        if image_file:
            ok = copy_image_resolving_stub(image_file, os.path.join(out_dir, texture_file_name))
            if not ok:
                # 如果下载失败且原文件是占位，则不要复制无效文件，避免“打不开”问题
                pass

    # 4) Auto-generate animations from atlas frame naming patterns
    # Group frames by trailing-number prefix (e.g., glow_01, glow_02, ..., or star1, star2...)
    auto_anim_dir = os.path.join(output_dir, "animations_auto")
    ensure_dir(auto_anim_dir)

    def split_name_series(nm: str) -> Optional[Tuple[str, int]]:
        # match base + digits at end
        m = re.match(r"^(.*?)(?:[_\-\s]?)(\d{1,4})$", nm)
        if not m:
            return None
        base = m.group(1)
        idx = int(m.group(2))
        base = base.strip().rstrip("_-. ")
        if not base:
            return None
        return (base, idx)

    auto_collected: List[Dict[str, Any]] = []
    default_fps = 24.0

    for comp_uuid, group in atlas_groups.items():
        # Build name->frames mapping
        series: Dict[str, List[Tuple[int, str]]] = {}
        for name in list(group["frames"].keys()):
            sp = split_name_series(name)
            if not sp:
                continue
            base, idx = sp
            series.setdefault(base, []).append((idx, name))

        for base, lst in series.items():
            lst.sort(key=lambda t: t[0])
            if len(lst) < 3:
                # too few frames, skip to avoid noise
                continue
            # try to ensure index continuity (heuristic)
            # allow small gaps but require at least 3 consecutive somewhere
            consecutive = 1
            for i in range(1, len(lst)):
                if lst[i][0] == lst[i-1][0] + 1:
                    consecutive += 1
                else:
                    consecutive = max(consecutive, 1)
            if consecutive < 3:
                continue

            frames_out = []
            for i, (_, fname) in enumerate(lst):
                frames_out.append({
                    "time": float(i) / default_fps,
                    "frame_name": fname
                })
            clip = {
                "name": base,
                "duration": float(len(lst)) / default_fps,
                "sample": default_fps,
                "tracks": [
                    {"type": "spriteFrame", "frames": frames_out}
                ],
                "source_atlas_uuid": comp_uuid,
                "source": "guessed"
            }
            out_file = os.path.join(auto_anim_dir, f"{safe_slug(base)}.anim.guessed.json")
            with open(out_file, "w", encoding="utf-8") as fh:
                json.dump(clip, fh, ensure_ascii=False, indent=2)
            auto_collected.append({"name": base, "path": out_file})

    # write index
    with open(os.path.join(auto_anim_dir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"clips": auto_collected, "note": "自动推断的序列动画，基于图集帧名的数字后缀"}, fh, ensure_ascii=False, indent=2)

    print("还原完成:")
    print(" - Spine 输出目录:", out_spine)
    print(" - 图集 输出目录:", out_atlas)
    print(" - 音频 输出目录:", os.path.join(output_dir, 'audio'))


if __name__ == "__main__":
    main()
