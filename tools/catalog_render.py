"""Preview image rendering for the Sculk Depths wiki catalog tool.

The renderer is deliberately dependency-light (Pillow only) and works without
starting Minecraft. It uses the mod's own model JSON when a model contains
``elements`` (cauldrons, pedestals, ...), and otherwise falls back to a
configurable formation such as ``cube``, ``slab``, ``stairs`` or ``cross``.

All dimensions are configurable in ``tools/catalog.config.json``.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, PngImagePlugin

from catalog_common import DEFAULT_FORMATIONS

COS30 = math.cos(math.radians(30.0))
SIN30 = 0.5

# Bump this whenever the renderer changes in a way that should invalidate
# existing preview images (the manifest stores the hash below).
RENDER_VERSION = 5

FACE_DEFS: dict[str, dict[str, Any]] = {
    "up": {
        "points": lambda x0, y0, z0, x1, y1, z1: [
            (x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)
        ],
        "default": "top",
        "shade": 1.0,
    },
    "down": {
        "points": lambda x0, y0, z0, x1, y1, z1: [
            (x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)
        ],
        "default": "bottom",
        "shade": 0.42,
    },
    "north": {
        "points": lambda x0, y0, z0, x1, y1, z1: [
            (x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (x0, y0, z0)
        ],
        "default": "side",
        "shade": 0.70,
    },
    "south": {
        "points": lambda x0, y0, z0, x1, y1, z1: [
            (x1, y1, z1), (x0, y1, z1), (x0, y0, z1), (x1, y0, z1)
        ],
        "default": "side",
        "shade": 0.82,
    },
    "east": {
        "points": lambda x0, y0, z0, x1, y1, z1: [
            (x1, y1, z1), (x1, y1, z0), (x1, y0, z0), (x1, y0, z1)
        ],
        "default": "side",
        "shade": 0.66,
    },
    "west": {
        "points": lambda x0, y0, z0, x1, y1, z1: [
            (x0, y1, z0), (x0, y1, z1), (x0, y0, z1), (x0, y0, z0)
        ],
        "default": "side",
        "shade": 0.55,
    },
}


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def frame_height(texture: Image.Image) -> int:
    """Height of a single frame in a (possibly animated) texture.

    Minecraft animated textures are vertical strips of square frames, e.g.
    16x1024. Model UVs address the first frame, so the renderer must not
    stretch all frames across the face.
    """
    if texture.height > texture.width and texture.height % texture.width == 0:
        return texture.width
    return texture.height


def lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


@dataclass
class Visual:
    identifier: str
    kind: str  # "model" | "formation" | "item"
    label: str
    model_name: str | None = None
    textures: dict[str, str] = field(default_factory=dict)
    model: dict[str, Any] | None = None
    formation: str = "cube"
    formation_def: dict[str, Any] = field(default_factory=dict)
    tints: dict[int, tuple[int, int, int]] = field(default_factory=dict)
    source_hash: str = ""


class TextureStore:
    """Resolves model/texture references from the mod and vanilla jars."""

    def __init__(self, mod_repo: Path):
        self.mod_repo = mod_repo
        self.assets = mod_repo / "src/main/resources/assets/sculk_depths"
        self.generated_assets = mod_repo / "src/main/generated/assets/sculk_depths"
        self.texture_root = self.assets / "textures"
        self.model_dirs = [
            self.generated_assets / "models/block",
            self.assets / "models/block",
        ]
        self.item_model_dirs = [
            self.generated_assets / "models/item",
            self.assets / "models/item",
        ]
        self.blockstate_dirs = [
            self.generated_assets / "blockstates",
            self.assets / "blockstates",
        ]
        self.vanilla_zip = self._find_vanilla_zip()
        self._model_cache: dict[str, dict[str, Any] | None] = {}
        self._image_cache: dict[str, Image.Image | None] = {}
        self._bytes_cache: dict[str, bytes | None] = {}
        self._placeholder = self._make_placeholder()

    def _find_vanilla_zip(self) -> Path | None:
        artifact_dir = self.mod_repo / "build/moddev/artifacts"
        if artifact_dir.exists():
            for candidate in sorted(artifact_dir.glob("*client-extra*.jar")):
                return candidate
        return None

    @staticmethod
    def _make_placeholder() -> Image.Image:
        image = Image.new("RGBA", (16, 16), (138, 138, 138, 255))
        draw = ImageDraw.Draw(image)
        for y in range(0, 16, 4):
            for x in range(0, 16, 4):
                if (x // 4 + y // 4) % 2 == 0:
                    draw.rectangle([x, y, x + 3, y + 3], fill=(112, 112, 112, 255))
        return image

    # ------------------------------------------------------------------ paths
    def _split_ref(self, ref: str, default_namespace: str = "sculk_depths") -> tuple[str, str]:
        ref = ref.strip()
        if ref.startswith("#"):
            return default_namespace, ref[1:]
        if ":" in ref:
            namespace, path = ref.split(":", 1)
            return namespace, path
        if ref.startswith("block/") or ref.startswith("item/"):
            return default_namespace, ref
        return default_namespace, f"block/{ref}"

    def _model_path(self, name: str) -> Path | None:
        namespace, path = self._split_ref(name, "sculk_depths")
        if namespace != "sculk_depths":
            return None
        if path.startswith("block/"):
            path = path[len("block/") :]
            directories = self.model_dirs
        elif path.startswith("item/"):
            path = path[len("item/") :]
            directories = self.item_model_dirs
        else:
            directories = [*self.model_dirs, *self.item_model_dirs]
        for directory in directories:
            candidate = directory / f"{path}.json"
            if candidate.exists():
                return candidate
        return None

    def _blockstate_path(self, block_id: str) -> Path | None:
        for directory in self.blockstate_dirs:
            candidate = directory / f"{block_id}.json"
            if candidate.exists():
                return candidate
        return None

    def read_json(self, path: Path) -> dict[str, Any] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def read_vanilla_json(self, name: str) -> dict[str, Any] | None:
        if not self.vanilla_zip:
            return None
        namespace, path = self._split_ref(name, "minecraft")
        zip_name = f"assets/{namespace}/models/{path}.json"
        try:
            with zipfile.ZipFile(self.vanilla_zip) as archive:
                return json.loads(archive.read(zip_name).decode("utf-8"))
        except (KeyError, OSError, json.JSONDecodeError):
            return None

    # ------------------------------------------------------------------ models
    def load_model(self, name: str, seen: set[str] | None = None) -> dict[str, Any] | None:
        if name in self._model_cache:
            return self._model_cache[name]
        seen = seen or set()
        if name in seen:
            return None
        seen.add(name)
        namespace, _ = self._split_ref(name, "sculk_depths")
        path = self._model_path(name)
        if path is not None:
            data = self.read_json(path)
        elif namespace == "minecraft":
            data = self.read_vanilla_json(name)
        else:
            data = None
        if data is None:
            self._model_cache[name] = None
            return None
        parent = data.get("parent")
        if isinstance(parent, str):
            parent_data = self.load_model(parent, seen)
            if parent_data is not None:
                merged = dict(parent_data)
                merged["textures"] = {**parent_data.get("textures", {}), **data.get("textures", {})}
                if "elements" in data:
                    merged["elements"] = data["elements"]
                for key in ("tints", "display", "overrides"):
                    if key in data:
                        merged[key] = data[key]
                merged["_parent"] = parent
                merged["_name"] = name
                self._model_cache[name] = merged
                return merged
        data = dict(data)
        data["_name"] = name
        self._model_cache[name] = data
        return data

    def pick_model_name(self, block_id: str, override: str | None = None) -> str | None:
        if override:
            return override
        if self._model_path(block_id) is not None:
            return block_id
        blockstate = self._blockstate_path(block_id)
        if blockstate is not None:
            data = self.read_json(blockstate)
            if data:
                models: list[str] = []
                variants = data.get("variants", {})
                if isinstance(variants, dict):
                    for value in variants.values():
                        for item in value if isinstance(value, list) else [value]:
                            if isinstance(item, dict) and isinstance(item.get("model"), str):
                                models.append(item["model"])
                for part in data.get("multipart", []):
                    apply = part.get("apply", {})
                    for item in apply if isinstance(apply, list) else [apply]:
                        if isinstance(item, dict) and isinstance(item.get("model"), str):
                            models.append(item["model"])
                # Multipart blocks (fences, walls) have separate post/side
                # models. Their inventory model shows the full shape.
                if data.get("multipart"):
                    inventory = f"{block_id}_inventory"
                    if self._model_path(inventory) is not None:
                        return inventory
                for preferred in ("inventory", "full", "level12", "height8", "bottom_left"):
                    for model in models:
                        if preferred in model:
                            return model
                if models:
                    return models[0]
        return block_id

    def resolve_texture_ref(self, ref: str, textures: dict[str, Any], seen: set[str] | None = None) -> str | None:
        seen = seen or set()
        if not ref:
            return None
        if ref.startswith("#"):
            key = ref[1:]
            if key in seen:
                return None
            seen.add(key)
            value = textures.get(key)
            if isinstance(value, str):
                return self.resolve_texture_ref(value, textures, seen)
            return None
        if ref.startswith("minecraft:") or ref.startswith("sculk_depths:"):
            return ref
        # Unprefixed refs are usually mod textures, but vanilla parent models
        # (e.g. item/template_spawn_egg) also use them. Prefer whichever exists.
        mod_ref = f"sculk_depths:{ref}"
        if self._texture_bytes(mod_ref) is not None:
            return mod_ref
        vanilla_ref = f"minecraft:{ref}"
        if self._texture_bytes(vanilla_ref) is not None:
            return vanilla_ref
        return mod_ref

    def model_textures(self, model: dict[str, Any] | None) -> dict[str, str]:
        if not model:
            return {}
        raw = model.get("textures", {})
        resolved: dict[str, str] = {}
        for key, value in raw.items():
            if not isinstance(value, str):
                continue
            ref = self.resolve_texture_ref(value, raw)
            if ref:
                resolved[key] = ref
        return resolved

    # ---------------------------------------------------------------- textures
    def _texture_bytes(self, ref: str) -> bytes | None:
        if ref in self._bytes_cache:
            return self._bytes_cache[ref]
        namespace, path = self._split_ref(ref, "sculk_depths")
        data: bytes | None = None
        if namespace == "sculk_depths":
            candidate = self.texture_root / f"{path}.png"
            if candidate.exists():
                data = candidate.read_bytes()
        elif self.vanilla_zip:
            zip_name = f"assets/{namespace}/textures/{path}.png"
            try:
                with zipfile.ZipFile(self.vanilla_zip) as archive:
                    data = archive.read(zip_name)
            except (KeyError, OSError):
                data = None
        self._bytes_cache[ref] = data
        return data

    def image(self, ref: str | None) -> Image.Image | None:
        if not ref:
            return None
        if ref in self._image_cache:
            return self._image_cache[ref]
        data = self._texture_bytes(ref)
        image: Image.Image | None = None
        if data:
            try:
                image = Image.open(io.BytesIO(data)).convert("RGBA")
            except OSError:
                image = None
        self._image_cache[ref] = image
        return image

    def slot_image(self, textures: dict[str, str], slot: str) -> Image.Image:
        chains = {
            "top": ("top", "end", "all", "texture", "side", "particle"),
            "bottom": ("bottom", "all", "texture", "side", "particle"),
            "side": ("side", "all", "texture", "front", "particle"),
            "cross": ("cross", "texture", "all", "side", "particle"),
            "front": ("front", "side", "all", "texture", "particle"),
            "back": ("back", "side", "all", "texture", "particle"),
        }
        for key in chains.get(slot, (slot, "all", "texture", "side", "particle")):
            ref = textures.get(key)
            image = self.image(ref)
            if image is not None:
                return image
        for ref in textures.values():
            image = self.image(ref)
            if image is not None:
                return image
        return self._placeholder

    def texture_hash(self, refs: list[str]) -> str:
        digest = hashlib.sha256()
        for ref in sorted(set(refs)):
            digest.update(ref.encode("utf-8"))
            data = self._texture_bytes(ref) or b""
            digest.update(data)
        return digest.hexdigest()


# --------------------------------------------------------------------- visuals
def _choose_formation(identifier: str, block_config: dict[str, Any], config: dict[str, Any]) -> str:
    if isinstance(block_config.get("formation"), str):
        return block_config["formation"]
    return choose_formation(identifier, config.get("formationRules", []))


def choose_formation(identifier: str, rules: list[dict[str, Any]]) -> str:
    for rule in rules:
        suffix = rule.get("suffix")
        if isinstance(suffix, str) and identifier.endswith(suffix):
            return rule.get("formation", "cube")
        pattern = rule.get("regex")
        if isinstance(pattern, str) and re.search(pattern, identifier):
            return rule.get("formation", "cube")
    return "cube"


def _adapt_cross_model(
    model: dict[str, Any],
    textures: dict[str, str],
    store: TextureStore,
) -> dict[str, Any] | None:
    """Fit a vanilla cross model's planes to the visible sprite content.

    Vanilla ``block/cross`` models are full-size planes with mostly transparent
    textures. Without this, small flowers/saplings look tiny in a 720p preview.
    """
    elements = model.get("elements") if model else None
    if not elements:
        return None
    texture = store.slot_image(textures, "cross")
    if texture is None:
        return None
    frame_h = frame_height(texture)
    frame = texture.crop((0, 0, texture.width, frame_h))
    bbox = frame.getchannel("A").getbbox()
    if not bbox:
        return None
    x0, y0, x1, y1 = bbox
    content_height = (y1 - y0) / frame_h * 16.0
    uv = [
        x0 * 16.0 / texture.width,
        y0 * 16.0 / frame_h,
        x1 * 16.0 / texture.width,
        y1 * 16.0 / frame_h,
    ]
    new_elements = []
    for element in elements:
        clone = json.loads(json.dumps(element))
        clone["from"][1] = 0
        clone["to"][1] = content_height
        for face in (clone.get("faces") or {}).values():
            if isinstance(face, dict):
                face["uv"] = uv
        new_elements.append(clone)
    adapted = dict(model)
    adapted["elements"] = new_elements
    return adapted


def build_block_visual(
    store: TextureStore,
    block_id: str,
    label: str,
    config: dict[str, Any],
) -> Visual:
    block_config = config.get("blocks", {}).get(block_id, {}) or {}
    render_mode = block_config.get("render", "auto")
    model_name = store.pick_model_name(block_id, block_config.get("model"))
    model = store.load_model(model_name) if model_name else None
    textures = store.model_textures(model)
    for slot, ref in (block_config.get("textures") or {}).items():
        textures[slot] = ref
    formation = _choose_formation(block_id, block_config, config)
    formation_def = config.get("formations", {}).get(formation, DEFAULT_FORMATIONS["cube"])
    elements = model.get("elements") if model else None
    kind = "formation"
    if render_mode == "model" and elements:
        kind = "model"
    elif render_mode == "auto" and elements:
        kind = "model"
    elif render_mode == "formation":
        kind = "formation"
        elements = None
    # Vanilla cross models (flowers, saplings, sprouts, ...) are two full-size
    # planes with mostly-transparent textures. Fit the planes to the visible
    # sprite so the plant is not tiny in the preview.
    model_parent = model.get("_parent") if model else None
    is_cross_model = isinstance(model_parent, str) and (
        model_parent.endswith(":block/cross") or model_parent.endswith(":block/tinted_cross")
    )
    if is_cross_model and render_mode != "model":
        adapted = _adapt_cross_model(model, textures, store)
        if adapted is not None:
            model = adapted
            elements = adapted.get("elements")
            kind = "model"
    refs = list(textures.values())
    digest = hashlib.sha256()
    digest.update(json.dumps({"kind": kind, "formation": formation, "formationDef": formation_def}, sort_keys=True).encode("utf-8"))
    if elements:
        digest.update(json.dumps(model, sort_keys=True).encode("utf-8"))
    digest.update(store.texture_hash(refs).encode("utf-8"))
    return Visual(
        identifier=block_id,
        kind=kind,
        label=label,
        model_name=model_name,
        textures=textures,
        model=model,
        formation=formation,
        formation_def=formation_def,
        source_hash=digest.hexdigest(),
    )


def build_item_visual(
    store: TextureStore,
    item_id: str,
    label: str,
    config: dict[str, Any],
    spawn_egg_tints: dict[str, tuple[int, int]] | None = None,
) -> Visual:
    item_config = config.get("items", {}).get(item_id, {}) or {}
    model_name = item_config.get("model") or f"sculk_depths:item/{item_id}"
    model = store.load_model(model_name)
    textures: dict[str, str] = store.model_textures(model) if model else {}
    layers = {key: ref for key, ref in textures.items() if key.startswith("layer")}
    if not layers:
        ref = item_config.get("texture") or f"sculk_depths:item/{item_id}"
        if store.image(ref) is None:
            fallback = f"sculk_depths:block/{item_id}"
            if store.image(fallback) is not None:
                ref = fallback
        layers = {"layer0": ref}

    tints: dict[int, tuple[int, int, int]] = {}
    for tint in (model or {}).get("tints", []) or []:
        index = tint.get("index")
        color = tint.get("default")
        if isinstance(index, int) and isinstance(color, int):
            tints[index] = ((color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF)
    if spawn_egg_tints and item_id in spawn_egg_tints:
        primary, secondary = spawn_egg_tints[item_id]
        tints[0] = ((primary >> 16) & 0xFF, (primary >> 8) & 0xFF, primary & 0xFF)
        tints[1] = ((secondary >> 16) & 0xFF, (secondary >> 8) & 0xFF, secondary & 0xFF)

    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            {
                "kind": "item",
                "model": model_name,
                "layers": layers,
                "tints": {str(key): value for key, value in tints.items()},
            },
            sort_keys=True,
        ).encode("utf-8")
    )
    if model:
        digest.update(json.dumps(model, sort_keys=True).encode("utf-8"))
    digest.update(store.texture_hash(list(layers.values())).encode("utf-8"))
    return Visual(
        identifier=item_id,
        kind="item",
        label=label,
        model_name=model_name,
        textures=layers,
        model=model,
        formation="item",
        formation_def=DEFAULT_FORMATIONS["item"],
        tints=tints,
        source_hash=digest.hexdigest(),
    )


# ------------------------------------------------------------------ rendering
def make_background(width: int, height: int, config: dict[str, Any]) -> Image.Image:
    background = config.get("background", {})
    top = hex_to_rgb(background.get("top", "#d4d7da"))
    bottom = hex_to_rgb(background.get("bottom", "#eef0f2"))
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(1, height - 1)
        draw.line([(0, y), (width, y)], fill=tuple(lerp(top[i], bottom[i], t) for i in range(3)))
    vignette = float(background.get("vignette", 0.0))
    if vignette > 0:
        gradient = Image.radial_gradient("L").resize((width, height), Image.LANCZOS)
        mask = gradient.point(lambda value: int(value * vignette))
        dark = Image.new("RGB", (width, height), hex_to_rgb(background.get("vignetteColor", "#000000")))
        image = Image.composite(dark, image, mask)
    return image.convert("RGBA")


def _box_faces(box: dict[str, Any], textures: dict[str, str]) -> list[dict[str, Any]]:
    x0, y0, z0 = (float(v) / 16.0 for v in box["from"])
    x1, y1, z1 = (float(v) / 16.0 for v in box["to"])
    faces: list[dict[str, Any]] = []
    box_textures = box.get("textures") or {}
    for name, definition in FACE_DEFS.items():
        slot = box_textures.get(name) or definition["default"]
        faces.append(
            {
                "points": definition["points"](x0, y0, z0, x1, y1, z1),
                "slot": slot,
                "shade": float(box.get("shade", definition["shade"])),
            }
        )
    return faces


def _rotation_matrix(rotation: dict[str, Any] | None) -> list[list[float]]:
    if not rotation:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    axis = rotation.get("axis", "y")
    angle = math.radians(float(rotation.get("angle", 0.0)))
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    if axis == "x":
        return [[1, 0, 0], [0, cos_a, -sin_a], [0, sin_a, cos_a]]
    if axis == "z":
        return [[cos_a, -sin_a, 0], [sin_a, cos_a, 0], [0, 0, 1]]
    return [[cos_a, 0, sin_a], [0, 1, 0], [-sin_a, 0, cos_a]]


def _apply_rotation(point: tuple[float, float, float], rotation: dict[str, Any] | None) -> tuple[float, float, float]:
    if not rotation:
        return point
    matrix = _rotation_matrix(rotation)
    origin = rotation.get("origin", [8, 8, 8])
    ox, oy, oz = (float(v) / 16.0 for v in origin)
    x, y, z = point[0] - ox, point[1] - oy, point[2] - oz
    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z + ox,
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z + oy,
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z + oz,
    )


def _element_faces(element: dict[str, Any], model_textures: dict[str, str], store: TextureStore) -> list[dict[str, Any]]:
    x0, y0, z0 = (float(v) / 16.0 for v in element["from"])
    x1, y1, z1 = (float(v) / 16.0 for v in element["to"])
    rotation = element.get("rotation")
    faces: list[dict[str, Any]] = []
    for name, definition in FACE_DEFS.items():
        face = (element.get("faces") or {}).get(name)
        if not isinstance(face, dict):
            continue
        ref = face.get("texture")
        if isinstance(ref, str):
            resolved = store.resolve_texture_ref(ref, model_textures)
        else:
            resolved = None
        if not resolved:
            resolved = model_textures.get(definition["default"])
        if not resolved:
            continue
        points = definition["points"](x0, y0, z0, x1, y1, z1)
        if rotation:
            points = [_apply_rotation(point, rotation) for point in points]
        faces.append(
            {
                "points": points,
                "ref": resolved,
                "shade": definition["shade"],
                "uv": face.get("uv"),
            }
        )
    return faces


def _cross_faces(textures: dict[str, str], store: TextureStore, height: float = 1.0) -> list[dict[str, Any]]:
    texture = store.slot_image(textures, "cross")
    bbox = None
    if texture is not None:
        frame_h = frame_height(texture)
        frame = texture.crop((0, 0, texture.width, frame_h))
        bbox = frame.getchannel("A").getbbox()
    if texture is not None and bbox:
        x0, y0, x1, y1 = bbox
        # Only map the visible part of the sprite and shrink the plane to the
        # sprite's content height, so small plants still fill the preview.
        content_height = (y1 - y0) / frame_h * height
        uv = [
            x0 * 16.0 / texture.width,
            y0 * 16.0 / frame_h,
            x1 * 16.0 / texture.width,
            y1 * 16.0 / frame_h,
        ]
    else:
        content_height = height
        uv = None
    faces: list[dict[str, Any]] = []
    planes = [
        [(0.5, content_height, 0.02), (0.5, content_height, 0.98), (0.5, 0.0, 0.98), (0.5, 0.0, 0.02)],
        [(0.02, content_height, 0.5), (0.98, content_height, 0.5), (0.98, 0.0, 0.5), (0.02, 0.0, 0.5)],
    ]
    for index, points in enumerate(planes):
        faces.append({"points": points, "slot": "cross", "shade": 0.95 if index == 0 else 0.82, "uv": uv})
        faces.append({"points": list(reversed(points)), "slot": "cross", "shade": 0.72 if index == 0 else 0.62, "uv": uv})
    return faces


def _visual_faces(visual: Visual, store: TextureStore) -> list[dict[str, Any]]:
    if visual.kind == "model" and visual.model:
        faces: list[dict[str, Any]] = []
        model_textures = visual.model.get("textures", {})
        for element in visual.model.get("elements", []):
            faces.extend(_element_faces(element, model_textures, store))
        if faces:
            return faces
    formation = visual.formation_def
    if formation.get("type") == "cross":
        return _cross_faces(visual.textures, store, float(formation.get("height", 16)) / 16.0)
    faces = []
    for box in formation.get("boxes", DEFAULT_FORMATIONS["cube"]["boxes"]):
        faces.extend(_box_faces(box, visual.textures))
    return faces


def _project(point: tuple[float, float, float]) -> tuple[float, float]:
    x, y, z = point
    return ((x - z) * COS30, (x + z) * SIN30 - y)


def _face_bounds(faces: list[dict[str, Any]]) -> tuple[float, float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    min_y = 0.0
    for face in faces:
        for point in face["points"]:
            px, py = _project(point)
            xs.append(px)
            ys.append(py)
            min_y = min(min_y, point[1])
    return min(xs), min(ys), max(xs), max(ys), min_y


def _affine_for_quad(points: list[tuple[float, float]]) -> tuple[float, float, float, float, float, float] | None:
    p0, p1, _, p3 = points
    a = p1[0] - p0[0]
    b = p3[0] - p0[0]
    c = p0[0]
    d = p1[1] - p0[1]
    e = p3[1] - p0[1]
    f = p0[1]
    det = a * e - b * d
    if abs(det) < 1e-9:
        return None
    # Inverse: u = A*x + B*y + C, v = D*x + E*y + F
    return (
        e / det,
        -b / det,
        (b * f - e * c) / det,
        -d / det,
        a / det,
        (d * c - a * f) / det,
    )


def _draw_face(
    canvas: Image.Image,
    face: dict[str, Any],
    transform: tuple[float, float, float],
    visual: Visual,
    store: TextureStore,
) -> None:
    scale, offset_x, offset_y = transform
    points = [
        (offset_x + _project(point)[0] * scale, offset_y + _project(point)[1] * scale)
        for point in face["points"]
    ]
    min_x = math.floor(min(p[0] for p in points)) - 1
    min_y = math.floor(min(p[1] for p in points)) - 1
    max_x = math.ceil(max(p[0] for p in points)) + 1
    max_y = math.ceil(max(p[1] for p in points)) + 1
    min_x = max(0, min_x)
    min_y = max(0, min_y)
    max_x = min(canvas.width, max_x)
    max_y = min(canvas.height, max_y)
    if max_x <= min_x or max_y <= min_y:
        return

    texture = store.image(face.get("ref")) if face.get("ref") else store.slot_image(visual.textures, face.get("slot", "side"))
    if texture is None:
        texture = store._placeholder
    affine = _affine_for_quad(points)
    if affine is None:
        return
    A, B, C, D, E, F = affine
    # Convert unit uv to source pixel coordinates. Animated textures are
    # vertical strips; model UVs address the first frame only.
    frame_h = frame_height(texture)
    uv = face.get("uv")
    if isinstance(uv, list) and len(uv) == 4:
        sx0 = float(uv[0]) / 16.0 * texture.width
        sy0 = float(uv[1]) / 16.0 * frame_h
        sx1 = float(uv[2]) / 16.0 * texture.width
        sy1 = float(uv[3]) / 16.0 * frame_h
    else:
        sx0, sy0, sx1, sy1 = 0.0, 0.0, float(texture.width), float(frame_h)
    sw = sx1 - sx0
    sh = sy1 - sy0
    if abs(sw) < 0.001 or abs(sh) < 0.001:
        return
    # Adjust affine coefficients for the cropped destination rectangle.
    C2 = A * min_x + B * min_y + C
    F2 = D * min_x + E * min_y + F
    coeffs = (A * sw, B * sw, C2 * sw + sx0, D * sh, E * sh, F2 * sh + sy0)
    try:
        transformed = texture.transform(
            (max_x - min_x, max_y - min_y),
            Image.Transform.AFFINE,
            coeffs,
            resample=Image.Resampling.NEAREST,
        )
    except (ValueError, OSError):
        return
    shade = float(face.get("shade", 1.0))
    if shade != 1.0:
        r, g, b, alpha = transformed.split()
        rgb = ImageEnhance.Brightness(Image.merge("RGB", (r, g, b))).enhance(shade)
        transformed = Image.merge("RGBA", (*rgb.split(), alpha))
    mask = Image.new("L", transformed.size, 0)
    ImageDraw.Draw(mask).polygon([(p[0] - min_x, p[1] - min_y) for p in points], fill=255)
    transformed.putalpha(ImageChops.multiply(transformed.getchannel("A"), mask))
    canvas.alpha_composite(transformed, (min_x, min_y))


def _draw_shadow(
    canvas: Image.Image,
    faces: list[dict[str, Any]],
    transform: tuple[float, float, float],
    config: dict[str, Any],
) -> None:
    shadow = config.get("shadow", {})
    if not shadow.get("enabled", True):
        return
    scale, offset_x, offset_y = transform
    min_y = _face_bounds(faces)[4]
    base_points: list[tuple[float, float]] = []
    for face in faces:
        for point in face["points"]:
            if abs(point[1] - min_y) < 1e-6:
                base_points.append((offset_x + _project(point)[0] * scale, offset_y + _project(point)[1] * scale))
    if not base_points:
        return
    cx = sum(p[0] for p in base_points) / len(base_points)
    cy = sum(p[1] for p in base_points) / len(base_points)
    spread = float(shadow.get("spread", 1.06))
    expanded = [(cx + (p[0] - cx) * spread, cy + (p[1] - cy) * spread) for p in base_points]
    layer = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(layer).polygon(expanded, fill=int(shadow.get("opacity", 105)))
    layer = layer.filter(ImageFilter.GaussianBlur(float(shadow.get("blur", 26))))
    dark = Image.new("RGBA", canvas.size, (0, 0, 0, 255))
    canvas.alpha_composite(Image.composite(dark, Image.new("RGBA", canvas.size, (0, 0, 0, 0)), layer))


def render_visual(visual: Visual, config: dict[str, Any], store: TextureStore) -> Image.Image:
    images = config.get("images", {})
    width = int(images.get("width", 1280))
    height = int(images.get("height", 720))
    canvas = make_background(width, height, images)
    if visual.kind == "item":
        return _render_item(canvas, visual, images, store)

    faces = _visual_faces(visual, store)
    if not faces:
        faces = _box_faces({"from": [0, 0, 0], "to": [16, 16, 16]}, visual.textures)
    min_x, min_y, max_x, max_y, lowest_y = _face_bounds(faces)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    fill = float(images.get("fill", 0.66))
    scale = min((width * fill) / span_x, (height * fill) / span_y)
    center_x = width / 2.0
    center_y = height / 2.0 + float(images.get("verticalOffset", 0))
    offset_x = center_x - ((min_x + max_x) / 2.0) * scale
    offset_y = center_y - ((min_y + max_y) / 2.0) * scale
    transform = (scale, offset_x, offset_y)
    _draw_shadow(canvas, faces, transform, {**images, "shadow": images.get("shadow", {})})
    faces.sort(key=lambda face: sum(sum(point) for point in face["points"]) / len(face["points"]))
    for face in faces:
        _draw_face(canvas, face, transform, visual, store)
    return canvas


def _tint_image(image: Image.Image, color: tuple[int, int, int] | None) -> Image.Image:
    if color is None:
        return image
    r, g, b, alpha = image.split()
    tint = Image.new("RGB", image.size, color)
    rgb = ImageChops.multiply(Image.merge("RGB", (r, g, b)), tint)
    return Image.merge("RGBA", (*rgb.split(), alpha))


def _render_item(canvas: Image.Image, visual: Visual, images: dict[str, Any], store: TextureStore) -> Image.Image:
    width, height = canvas.size
    layers = [
        (key, ref) for key, ref in sorted(visual.textures.items()) if key.startswith("layer")
    ]
    if not layers:
        layers = [("layer0", visual.textures.get("item") or visual.textures.get("all"))]

    layer_images: list[tuple[int, Image.Image]] = []
    for key, ref in layers:
        layer = store.image(ref)
        if layer is None:
            continue
        frame_h = frame_height(layer)
        if frame_h != layer.height:
            layer = layer.crop((0, 0, layer.width, frame_h))
        try:
            index = int(key.replace("layer", "") or 0)
        except ValueError:
            index = 0
        layer_images.append((index, _tint_image(layer, visual.tints.get(index))))

    if layer_images:
        texture = Image.new(
            "RGBA",
            (
                max(layer.width for _, layer in layer_images),
                max(layer.height for _, layer in layer_images),
            ),
            (0, 0, 0, 0),
        )
        for _, layer in layer_images:
            texture.alpha_composite(layer, (0, 0))
    else:
        texture = store._placeholder

    bbox = texture.getchannel("A").getbbox()
    if bbox:
        texture = texture.crop(bbox)
    item_fill = float(images.get("itemFill", 0.45))
    max_w = int(width * item_fill)
    max_h = int(height * item_fill * 1.25)
    scale = min(max_w / texture.width, max_h / texture.height)
    new_size = (max(1, int(texture.width * scale)), max(1, int(texture.height * scale)))
    sprite = texture.resize(new_size, Image.Resampling.NEAREST)
    x = (width - sprite.width) // 2
    y = (height - sprite.height) // 2
    # Soft elliptical shadow under the sprite.
    shadow = images.get("shadow", {})
    if shadow.get("enabled", True):
        layer = Image.new("L", canvas.size, 0)
        ellipse = [
            x + sprite.width * 0.12,
            y + sprite.height * 0.78,
            x + sprite.width * 0.88,
            y + sprite.height * 0.78 + max(18, sprite.height * 0.16),
        ]
        ImageDraw.Draw(layer).ellipse(ellipse, fill=int(shadow.get("opacity", 105)))
        layer = layer.filter(ImageFilter.GaussianBlur(float(shadow.get("blur", 26))))
        dark = Image.new("RGBA", canvas.size, (0, 0, 0, 255))
        canvas.alpha_composite(Image.composite(dark, Image.new("RGBA", canvas.size, (0, 0, 0, 0)), layer))
    canvas.alpha_composite(sprite, (x, y))
    return canvas


def save_image(image: Image.Image, path: Path, label: str, kind: str, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = PngImagePlugin.PngInfo()
    noun = "item" if kind == "item" else "block"
    metadata.add_text("Title", f"{label} {noun} - Sculk Depths Minecraft mod")
    metadata.add_text(
        "Description",
        f"{label} is a {noun} added by the Sculk Depths Minecraft mod. "
        f"Preview render generated from the mod's own textures.",
    )
    metadata.add_text("Keywords", f"Sculk Depths, Minecraft mod, {label}, {noun}, wiki")
    metadata.add_text("Software", "Sculk Depths wiki catalog tool")
    compress_level = int(config.get("compressLevel", 6))
    image.convert("RGB").save(path, "PNG", pnginfo=metadata, compress_level=compress_level)


def visual_hash(visual: Visual, images: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(visual.source_hash.encode("utf-8"))
    digest.update(
        json.dumps(
            {
                "renderer": RENDER_VERSION,
                "width": images.get("width"),
                "height": images.get("height"),
                "fill": images.get("fill"),
                "background": images.get("background"),
                "shadow": images.get("shadow"),
            },
            sort_keys=True,
        ).encode("utf-8")
    )
    return digest.hexdigest()
