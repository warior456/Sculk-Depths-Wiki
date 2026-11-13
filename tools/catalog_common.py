"""Shared helpers for the Sculk Depths wiki catalog tool.

This module only deals with *reading* the mod: config, Java registrations,
language strings, block properties, tags and loot tables. Rendering and file
updates live in ``catalog_render.py`` and ``catalog_tool.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Root of the repository this script lives in. Used only as the default when
# neither --wiki-repo, SCULK_DEPTHS_WIKI_DIR nor ``wikiRepo`` in the config
# points somewhere else.
SCRIPT_ROOT = Path(__file__).resolve().parent.parent
WIKI_ROOT = SCRIPT_ROOT
DEFAULT_CONFIG_PATH = SCRIPT_ROOT / "tools" / "catalog.config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    # Both repositories are configurable. Relative paths are resolved from the
    # current working directory; ``~`` is expanded.
    "wikiRepo": None,
    "modRepo": None,
    "manifest": "static/.catalog-manifest.json",
    "images": {
        "width": 1280,
        "height": 720,
        "fill": 0.66,
        "itemFill": 0.45,
        "verticalOffset": 12,
        "background": {
            "top": "#d4d7da",
            "bottom": "#eef0f2",
            "vignette": 0.12,
            "vignetteColor": "#000000",
        },
        "shadow": {
            "enabled": True,
            "opacity": 105,
            "blur": 26,
            "spread": 1.06,
        },
        "textureFilter": "nearest",
        "compressLevel": 6,
    },
    "catalogs": {
        "blocks": {
            "page": "wiki/feature_catalog/catalog_blocks.md",
            "source": "blocks",
            "imageDir": "static/blocks",
            "urlPrefix": "/static/blocks",
            "alt": "{label} block - Sculk Depths Minecraft mod",
            "title": "{label} block from the Sculk Depths Minecraft mod",
            "includeProperties": True,
        },
        "items": {
            "page": "wiki/feature_catalog/catalog_items.md",
            "source": "items",
            "imageDir": "static/items",
            "urlPrefix": "/static/items",
            "alt": "{label} item - Sculk Depths Minecraft mod",
            "title": "{label} item from the Sculk Depths Minecraft mod",
            "includeProperties": False,
        },
    },
    "formationRules": [
        {"suffix": "_wall_hanging_sign", "formation": "hanging_sign"},
        {"suffix": "_hanging_sign", "formation": "hanging_sign"},
        {"suffix": "_wall_sign", "formation": "sign"},
        {"suffix": "_sign", "formation": "sign"},
        {"suffix": "_fence_gate", "formation": "fence_gate"},
        {"suffix": "_fence", "formation": "fence"},
        {"suffix": "_door", "formation": "door"},
        {"suffix": "_trapdoor", "formation": "trapdoor"},
        {"suffix": "_pressure_plate", "formation": "pressure_plate"},
        {"suffix": "_button", "formation": "button"},
        {"suffix": "_stairs", "formation": "stairs"},
        {"suffix": "_slab", "formation": "slab"},
        {"suffix": "_wall", "formation": "wall"},
        {"suffix": "_pane", "formation": "pane"},
        {"suffix": "_bars", "formation": "bars"},
        {"suffix": "_carpet", "formation": "carpet"},
        {"suffix": "_layer", "formation": "layer"},
        {"suffix": "_sapling", "formation": "cross"},
        {"suffix": "_sprouts", "formation": "cross"},
        {"suffix": "_bush", "formation": "cross"},
        {"suffix": "_shroom", "formation": "cross"},
        {"suffix": "_vines", "formation": "cross"},
        {"suffix": "_vine", "formation": "cross"},
        {"suffix": "_plant", "formation": "cross"},
        {"suffix": "_flower", "formation": "cross"},
        {"suffix": "_roots", "formation": "cross"},
        {"suffix": "_torch", "formation": "torch"},
        {"suffix": "_chain", "formation": "chain"},
    ],
    "formations": {},
    "blocks": {},
    "items": {},
    "exclude": {"blocks": [], "items": []},
}

# Fallback geometry used when a block has no model elements. Coordinates are
# Minecraft model units (0..16). Keep this in sync with tools/README.md.
DEFAULT_FORMATIONS: dict[str, Any] = {
    "cube": {
        "boxes": [{"from": [0, 0, 0], "to": [16, 16, 16]}],
    },
    "slab": {
        "boxes": [{"from": [0, 0, 0], "to": [16, 8, 16]}],
    },
    "slab_top": {
        "boxes": [{"from": [0, 8, 0], "to": [16, 16, 16]}],
    },
    "stairs": {
        "boxes": [
            {"from": [0, 0, 0], "to": [16, 8, 16]},
            {"from": [0, 8, 8], "to": [16, 16, 16]},
        ],
    },
    "wall": {
        "boxes": [
            {"from": [5, 0, 5], "to": [11, 16, 11]},
            {"from": [0, 0, 5], "to": [5, 10, 11]},
            {"from": [11, 0, 5], "to": [16, 10, 11]},
        ],
    },
    "fence": {
        "boxes": [
            {"from": [6, 0, 6], "to": [10, 16, 10]},
            {"from": [0, 6, 7], "to": [6, 10, 9]},
            {"from": [10, 6, 7], "to": [16, 10, 9]},
            {"from": [7, 6, 0], "to": [9, 10, 6]},
            {"from": [7, 6, 10], "to": [9, 10, 16]},
        ],
    },
    "fence_gate": {
        "boxes": [
            {"from": [0, 0, 0], "to": [2, 16, 4]},
            {"from": [14, 0, 0], "to": [16, 16, 4]},
            {"from": [2, 2, 1], "to": [14, 16, 3]},
        ],
    },
    "door": {
        "boxes": [
            {"from": [7, 0, 0], "to": [9, 16, 16]},
        ],
    },
    "trapdoor": {
        "boxes": [{"from": [0, 0, 0], "to": [16, 3, 16]}],
    },
    "button": {
        "boxes": [{"from": [5, 0, 5], "to": [11, 2, 11]}],
    },
    "pressure_plate": {
        "boxes": [{"from": [0, 0, 0], "to": [16, 1, 16]}],
    },
    "sign": {
        "boxes": [
            {"from": [0, 0, 6], "to": [16, 16, 9]},
            {"from": [1, -4, 7], "to": [3, 12, 9]},
            {"from": [13, -4, 7], "to": [15, 12, 9]},
        ],
    },
    "hanging_sign": {
        "boxes": [
            {"from": [0, 0, 6], "to": [16, 14, 9]},
            {"from": [1, 14, 7], "to": [3, 16, 9]},
            {"from": [13, 14, 7], "to": [15, 16, 9]},
        ],
    },
    "pane": {
        "boxes": [{"from": [7, 0, 0], "to": [9, 16, 16]}],
    },
    "bars": {
        "boxes": [
            {"from": [7, 0, 7], "to": [9, 16, 9]},
            {"from": [7, 4, 0], "to": [9, 6, 16]},
            {"from": [0, 4, 7], "to": [16, 6, 9]},
        ],
    },
    "carpet": {
        "boxes": [{"from": [0, 0, 0], "to": [16, 1, 16]}],
    },
    "layer": {
        "boxes": [{"from": [0, 0, 0], "to": [16, 8, 16]}],
    },
    "torch": {
        "boxes": [
            {"from": [7, 0, 7], "to": [9, 10, 9]},
            {"from": [6, 10, 6], "to": [10, 12, 10]},
        ],
    },
    "chain": {
        "boxes": [{"from": [7, 0, 7], "to": [9, 16, 9]}],
    },
    "cross": {"type": "cross", "height": 16},
    "item": {"type": "item"},
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base``."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path | None = None) -> dict[str, Any]:
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        user_config = json.load(handle)
    config = deep_merge(DEFAULT_CONFIG, user_config)
    config["formations"] = deep_merge(DEFAULT_FORMATIONS, config.get("formations") or {})
    return config


def strip_java_comments(source: str) -> str:
    """Remove // and /* */ comments while preserving string literals."""
    out: list[str] = []
    i = 0
    length = len(source)
    in_string = in_char = in_line = in_block = False
    escaped = False
    while i < length:
        char = source[i]
        nxt = source[i + 1] if i + 1 < length else ""
        if in_line:
            if char == "\n":
                in_line = False
                out.append(char)
            i += 1
            continue
        if in_block:
            if char == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if in_string or in_char:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif in_string and char == '"':
                in_string = False
            elif in_char and char == "'":
                in_char = False
            i += 1
            continue
        if char == "/" and nxt == "/":
            in_line = True
            i += 2
            continue
        if char == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if char == '"':
            in_string = True
        elif char == "'":
            in_char = True
        out.append(char)
        i += 1
    return "".join(out)


def find_matching_paren(source: str, start: int) -> int:
    """Return the index of the ``)`` matching the ``(`` at ``start``."""
    depth = 0
    in_string = in_char = False
    escaped = False
    for i in range(start, len(source)):
        char = source[i]
        if in_string or in_char:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif in_string and char == '"':
                in_string = False
            elif in_char and char == "'":
                in_char = False
            continue
        if char == '"':
            in_string = True
        elif char == "'":
            in_char = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


_REGISTRATION_RE = re.compile(
    r"register(?P<kind>BlockWithoutBlockItem|Block|Item)\s*\(\s*\"(?P<id>[^\"]+)\""
)
_DECLARATION_RE = re.compile(
    r"public\s+static\s+final\s+Block\s+(?P<constant>[A-Z0-9_]+)\s*=\s*"
    r"register(?P<kind>BlockWithoutBlockItem|Block)\s*\(\s*\"(?P<id>[^\"]+)\""
)


def scan_registrations(java_path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Return ``{id: {"kind": ..., "body": ...}}`` and constant -> id."""
    if not java_path.exists():
        return {}, {}
    source = strip_java_comments(java_path.read_text(encoding="utf-8"))
    registrations: dict[str, dict[str, Any]] = {}
    for match in _REGISTRATION_RE.finditer(source):
        paren = source.find("(", match.start())
        close = find_matching_paren(source, paren)
        if close == -1:
            continue
        registrations[match.group("id")] = {
            "kind": match.group("kind"),
            "body": source[paren + 1 : close],
        }
    constants: dict[str, str] = {}
    for match in _DECLARATION_RE.finditer(source):
        constants[match.group("constant")] = match.group("id")
    return registrations, constants


_JSON_PAIR_RE = re.compile(r'"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"')


def load_lang(lang_path: Path) -> dict[str, str]:
    """Read key/value pairs from en_us.json.

    The mod's language file contains ``//`` comments, so it is not valid JSON.
    A small regex based reader is intentionally used instead.
    """
    if not lang_path.exists():
        return {}
    text = lang_path.read_text(encoding="utf-8")
    result: dict[str, str] = {}
    for match in _JSON_PAIR_RE.finditer(text):
        key = json.loads('"' + match.group(1) + '"')
        value = json.loads('"' + match.group(2) + '"')
        result[key] = value
    return result


def load_spawn_egg_tints(mod_repo: Path) -> dict[str, tuple[int, int]]:
    """Return ``{item_id: (primary, secondary)}`` for mod spawn eggs."""
    path = mod_repo / "src/main/java/net/ugi/sculk_depths/item/ModItems.java"
    if not path.exists():
        return {}
    source = strip_java_comments(path.read_text(encoding="utf-8"))
    pattern = re.compile(
        r'registerItem\s*\(\s*"(?P<id>[^"]+_spawn_egg)"\s*,\s*'
        r"new\s+SpawnEggItem\s*\(\s*[^,]+,\s*(?P<primary>\d+)\s*,\s*(?P<secondary>\d+)"
    )
    tints: dict[str, tuple[int, int]] = {}
    for match in pattern.finditer(source):
        tints[match.group("id")] = (int(match.group("primary")), int(match.group("secondary")))
    return tints


def titleize(identifier: str) -> str:
    return " ".join(part.capitalize() for part in identifier.replace("-", "_").split("_") if part)


def display_name(identifier: str, lang: dict[str, str], kind: str = "block") -> str:
    keys = []
    if kind == "item":
        keys.append(f"item.sculk_depths.{identifier}")
        keys.append(f"block.sculk_depths.{identifier}")
    else:
        keys.append(f"block.sculk_depths.{identifier}")
        keys.append(f"item.sculk_depths.{identifier}")
    for key in keys:
        value = lang.get(key)
        if value and value.strip() and value.strip().upper() != "WIP":
            return value.strip()
    return titleize(identifier)


_NUMBER = r"-?(?:\d+(?:\.\d*)?|\.\d+)"


def _parse_number(value: str) -> float:
    return float(value.rstrip("fFdD"))


# Vanilla values used by ``ofFullCopy(Blocks.X)``. If a new vanilla reference is
# added, add its hardness / blast resistance here (or use an explicit strength()
# override in the mod source).
VANILLA_BLOCK_PROPERTIES: dict[str, dict[str, float]] = {
    "BROWN_MUSHROOM": {"hardness": 0.0, "blast": 0.0},
    "CAULDRON": {"hardness": 2.0, "blast": 2.0},
    "DEEPSLATE": {"hardness": 3.0, "blast": 6.0},
    "DIAMOND_BLOCK": {"hardness": 5.0, "blast": 6.0},
    "FARMLAND": {"hardness": 0.6, "blast": 0.6},
    "FURNACE": {"hardness": 3.5, "blast": 3.5},
    "GLASS": {"hardness": 0.3, "blast": 0.3},
    "MUSHROOM_STEM": {"hardness": 0.2, "blast": 0.2},
    "NETHER_PORTAL": {"hardness": -1.0, "blast": 0.0},
    "NETHERITE_BLOCK": {"hardness": 50.0, "blast": 1200.0},
    "OAK_BUTTON": {"hardness": 0.5, "blast": 0.5},
    "OAK_DOOR": {"hardness": 3.0, "blast": 3.0},
    "OAK_FENCE": {"hardness": 2.0, "blast": 3.0},
    "OAK_FENCE_GATE": {"hardness": 2.0, "blast": 3.0},
    "OAK_HANGING_SIGN": {"hardness": 1.0, "blast": 1.0},
    "OAK_LEAVES": {"hardness": 0.2, "blast": 0.2},
    "OAK_LOG": {"hardness": 2.0, "blast": 2.0},
    "OAK_PLANKS": {"hardness": 2.0, "blast": 3.0},
    "OAK_PRESSURE_PLATE": {"hardness": 0.5, "blast": 0.5},
    "OAK_SAPLING": {"hardness": 0.0, "blast": 0.0},
    "OAK_SIGN": {"hardness": 1.0, "blast": 1.0},
    "OAK_SLAB": {"hardness": 2.0, "blast": 3.0},
    "OAK_STAIRS": {"hardness": 2.0, "blast": 3.0},
    "OAK_TRAPDOOR": {"hardness": 3.0, "blast": 3.0},
    "OAK_WALL_HANGING_SIGN": {"hardness": 1.0, "blast": 1.0},
    "OAK_WALL_SIGN": {"hardness": 1.0, "blast": 1.0},
    "OAK_WOOD": {"hardness": 2.0, "blast": 2.0},
    "OBSIDIAN": {"hardness": 50.0, "blast": 1200.0},
    "REINFORCED_DEEPSLATE": {"hardness": 55.0, "blast": 1200.0},
    "SHORT_GRASS": {"hardness": 0.0, "blast": 0.0},
    "STONE": {"hardness": 1.5, "blast": 6.0},
    "STONE_BUTTON": {"hardness": 0.5, "blast": 0.5},
    "STONE_PRESSURE_PLATE": {"hardness": 0.5, "blast": 0.5},
    "STRIPPED_OAK_LOG": {"hardness": 2.0, "blast": 2.0},
    "STRIPPED_OAK_WOOD": {"hardness": 2.0, "blast": 2.0},
    "SWEET_BERRY_BUSH": {"hardness": 0.0, "blast": 0.0},
    "WATER": {"hardness": 100.0, "blast": 100.0},
}


def parse_block_properties(
    block_id: str,
    registrations: dict[str, dict[str, Any]],
    constant_to_id: dict[str, str],
    cache: dict[str, dict[str, Any]] | None = None,
    seen: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve hardness, blast resistance and tool requirement for a block."""
    cache = cache if cache is not None else {}
    if block_id in cache:
        return cache[block_id]
    seen = seen or set()
    if block_id in seen:
        return {}
    seen.add(block_id)
    body = registrations.get(block_id, {}).get("body", "")
    result: dict[str, Any] = {}

    copy = re.search(r"\.ofFullCopy\(\s*(?:(\w+)\.)?([A-Z0-9_]+)\s*\)", body)
    if copy:
        qualifier, name = copy.groups()
        if qualifier in (None, "ModBlocks"):
            target = constant_to_id.get(name)
            if target and target in registrations:
                inherited = parse_block_properties(target, registrations, constant_to_id, cache, seen)
                result.update({k: v for k, v in inherited.items() if k in ("hardness", "blast", "requiresTool")})
        elif qualifier == "Blocks":
            vanilla = VANILLA_BLOCK_PROPERTIES.get(name)
            if vanilla:
                result.update(vanilla)

    strength = re.search(
        rf"\.strength\(\s*({_NUMBER})[fFdD]?\s*(?:,\s*({_NUMBER})[fFdD]?\s*)?\)",
        body,
    )
    if strength:
        hardness = _parse_number(strength.group(1))
        blast = _parse_number(strength.group(2)) if strength.group(2) else hardness
        result["hardness"] = hardness
        result["blast"] = blast
    if ".instabreak()" in body:
        result["hardness"] = 0.0
        result["blast"] = 0.0
    if ".requiresCorrectToolForDrops()" in body:
        result["requiresTool"] = True
    else:
        result.setdefault("requiresTool", False)
    seen.discard(block_id)
    cache[block_id] = result
    return result


def load_tag_values(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    values = []
    for value in data.get("values", []):
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, dict) and isinstance(value.get("id"), str):
            values.append(value["id"])
    return values


def load_tool_data(mod_repo: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return block -> tool and block -> required tier."""
    tools: dict[str, str] = {}
    tiers: dict[str, str] = {}
    tag_roots = [
        mod_repo / "src/main/generated/data/minecraft/tags/block",
        mod_repo / "src/main/resources/data/minecraft/tags/block",
    ]
    for root in tag_roots:
        for tool in ("pickaxe", "axe", "shovel", "hoe"):
            for value in load_tag_values(root / "mineable" / f"{tool}.json"):
                if value.startswith("sculk_depths:"):
                    tools.setdefault(value.split(":", 1)[1], tool)
        for tier in ("stone", "iron", "diamond"):
            for value in load_tag_values(root / f"needs_{tier}_tool.json"):
                if value.startswith("sculk_depths:"):
                    tiers.setdefault(value.split(":", 1)[1], tier)
    return tools, tiers


def _loot_entries(entry: dict[str, Any]) -> list[tuple[str, int]]:
    entries: list[tuple[str, int]] = []
    entry_type = entry.get("type", "")
    if entry_type == "minecraft:item" and isinstance(entry.get("name"), str):
        count = 1
        for function in entry.get("functions", []):
            if function.get("function") == "minecraft:set_count":
                value = function.get("count", 1)
                if isinstance(value, (int, float)):
                    count = int(value)
                elif isinstance(value, dict):
                    count = int(value.get("max", value.get("min", 1)) or 1)
        entries.append((entry["name"], count))
    elif entry_type in ("minecraft:alternatives", "minecraft:group", "minecraft:sequence"):
        for child in entry.get("children", []):
            entries.extend(_loot_entries(child))
    return entries


def load_drops(mod_repo: Path, block_id: str, lang: dict[str, str]) -> list[tuple[str, int]]:
    candidates = [
        mod_repo / "src/main/generated/data/sculk_depths/loot_table/blocks" / f"{block_id}.json",
        mod_repo / "src/main/resources/data/sculk_depths/loot_table/blocks" / f"{block_id}.json",
        mod_repo / "src/main/generated/data/sculk_depths/loot_tables/blocks" / f"{block_id}.json",
        mod_repo / "src/main/resources/data/sculk_depths/loot_tables/blocks" / f"{block_id}.json",
    ]
    path = next((candidate for candidate in candidates if candidate.exists()), None)
    if path is None:
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    drops: list[tuple[str, int]] = []
    for pool in data.get("pools", []):
        for entry in pool.get("entries", []):
            drops.extend(_loot_entries(entry))
    # Keep order but remove duplicate name/count pairs.
    seen: set[tuple[str, int]] = set()
    unique = []
    for item in drops:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def drop_label(name: str, lang: dict[str, str]) -> str:
    if name.startswith("sculk_depths:"):
        identifier = name.split(":", 1)[1]
        return display_name(identifier, lang, "item")
    if name.startswith("minecraft:"):
        return titleize(name.split(":", 1)[1])
    return titleize(name)


def format_number(value: float) -> str:
    if value < 0:
        return "Unbreakable"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def format_tool(block_id: str, tools: dict[str, str], tiers: dict[str, str], requires_tool: bool) -> str | None:
    tool = tools.get(block_id)
    tier = tiers.get(block_id)
    if tool and tier:
        return f"{tier.title()} {tool} or better"
    if tool:
        return tool.title()
    if tier:
        return f"{tier.title()} tool or better"
    if requires_tool:
        return "Correct tool required"
    return None
