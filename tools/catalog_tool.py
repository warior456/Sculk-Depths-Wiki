#!/usr/bin/env python3
"""Automatically keep the Sculk Depths wiki feature catalogs in sync.

The tool is conservative: it only *adds* missing ``###`` sections. Existing
sections (including hand-written descriptions, recipes and screenshots) are
never rewritten. New entries get automatically generated preview images and a
small set of factual properties (hardness, blast resistance, tool, drops).

See ``tools/README.md`` for the configuration format.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from PIL import Image  # noqa: F401  (fail fast with a clear dependency error)

from catalog_common import (
    DEFAULT_CONFIG_PATH,
    SCRIPT_ROOT,
    display_name,
    drop_label,
    format_number,
    format_tool,
    load_config,
    load_drops,
    load_lang,
    load_spawn_egg_tints,
    load_tool_data,
    parse_block_properties,
    scan_registrations,
    titleize,
)
from catalog_render import (
    TextureStore,
    build_block_visual,
    build_item_visual,
    render_visual,
    save_image,
    visual_hash,
)

HEADING_RE = re.compile(r"(?m)^###[ \t]+(.+?)[ \t]*$")
PLACEHOLDER_TITLES = {"..."}


def normalize(value: str) -> str:
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def resolve_wiki_root(
    explicit: str | None,
    config: dict[str, Any],
    script_root: Path = SCRIPT_ROOT,
) -> Path:
    """Resolve the wiki repository root.

    Priority: ``--wiki-repo`` > ``SCULK_DEPTHS_WIKI_DIR`` > ``wikiRepo`` in the
    config > the repository this script lives in.
    """
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("SCULK_DEPTHS_WIKI_DIR")
    if env:
        candidates.append(Path(env))
    configured = config.get("wikiRepo")
    if configured:
        candidates.append(Path(configured))
    candidates.append(script_root)

    checked: list[str] = []
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if str(resolved) in checked:
            continue
        checked.append(str(resolved))
        if (resolved / "tools" / "catalog_tool.py").exists() or (resolved / "wiki").is_dir():
            return resolved
    raise FileNotFoundError(
        "Could not find the Sculk Depths wiki repository. Pass --wiki-repo <path> or "
        "set SCULK_DEPTHS_WIKI_DIR. Checked:\n  " + "\n  ".join(checked)
    )


def find_mod_repo(explicit: str | None, config: dict[str, Any], wiki_root: Path) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("SCULK_DEPTHS_DIR")
    if env:
        candidates.append(Path(env))
    configured = config.get("modRepo")
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        [
            wiki_root.parent / "Sculk-Depths",
            wiki_root.parent / "Sculk-Depths-main",
            wiki_root / ".mod-sources",
            wiki_root / "mod-sources",
            Path.home() / "IdeaProjects" / "Sculk-Depths",
            Path.home() / "programmeren" / "Sculk-Depths",
            Path.cwd(),
        ]
    )
    checked: list[str] = []
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if str(resolved) in checked:
            continue
        checked.append(str(resolved))
        if (resolved / "src/main/java/net/ugi/sculk_depths/block/ModBlocks.java").exists():
            return resolved
    raise FileNotFoundError(
        "Could not find the Sculk Depths mod sources. Pass --mod-repo <path> or set "
        "SCULK_DEPTHS_DIR. Checked:\n  " + "\n  ".join(checked)
    )


def resolve_image_config(config: dict[str, Any], args: argparse.Namespace) -> None:
    images = config.setdefault("images", {})
    if args.resolution:
        value = args.resolution.lower().rstrip("p")
        if "x" in value:
            width, height = value.split("x", 1)
            images["width"] = int(width)
            images["height"] = int(height)
        else:
            presets = {"720": (1280, 720), "1080": (1920, 1080), "1440": (2560, 1440), "2160": (3840, 2160)}
            if value not in presets:
                raise SystemExit(f"Unknown resolution preset: {args.resolution}")
            images["width"], images["height"] = presets[value]
    if args.width:
        images["width"] = args.width
    if args.height:
        images["height"] = args.height


def collect_blocks(config: dict[str, Any], mod_repo: Path) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, Any]], dict[str, str]]:
    lang = load_lang(mod_repo / "src/main/resources/assets/sculk_depths/lang/en_us.json")
    registrations, constants = scan_registrations(
        mod_repo / "src/main/java/net/ugi/sculk_depths/block/ModBlocks.java"
    )
    excluded = set(config.get("exclude", {}).get("blocks", []))
    blocks = {
        identifier: entry
        for identifier, entry in registrations.items()
        if entry.get("kind") == "Block" and identifier not in excluded
    }
    return blocks, constants, registrations, lang


def collect_items(config: dict[str, Any], mod_repo: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    lang = load_lang(mod_repo / "src/main/resources/assets/sculk_depths/lang/en_us.json")
    registrations, _ = scan_registrations(
        mod_repo / "src/main/java/net/ugi/sculk_depths/item/ModItems.java"
    )
    excluded = set(config.get("exclude", {}).get("items", []))
    items = {
        identifier: entry
        for identifier, entry in registrations.items()
        if entry.get("kind") == "Item" and identifier not in excluded
    }
    return items, lang


def format_drops(block_id: str, drops: list[tuple[str, int]], lang: dict[str, str]) -> str | None:
    if not drops:
        return None
    if len(drops) == 1 and drops[0] == (f"sculk_depths:{block_id}", 1):
        return "Itself"
    parts: list[str] = []
    for name, count in drops:
        if name == f"sculk_depths:{block_id}":
            label = "Itself"
        else:
            label = drop_label(name, lang)
        if count > 1:
            label += f" (x{count})"
        parts.append(label)
    return ", ".join(parts)


def property_lines(
    block_id: str,
    entry: dict[str, Any],
    config: dict[str, Any],
    registrations: dict[str, dict[str, Any]],
    constants: dict[str, str],
    property_cache: dict[str, dict[str, Any]],
    tools: dict[str, str],
    tiers: dict[str, str],
    lang: dict[str, str],
) -> list[str]:
    properties = parse_block_properties(block_id, registrations, constants, property_cache)
    lines: list[str] = []
    if "hardness" in properties:
        lines.append(f"- Hardness: {format_number(properties['hardness'])}")
    if "blast" in properties and properties.get("blast") != properties.get("hardness"):
        lines.append(f"- Blast resistance: {format_number(properties['blast'])}")
    tool = format_tool(block_id, tools, tiers, bool(properties.get("requiresTool")))
    if tool:
        lines.append(f"- Tool: {tool}")
    drops = format_drops(block_id, load_drops(config["_modRepo"], block_id, lang), lang)
    if drops:
        lines.append(f"- Drops: {drops}")
    return lines


def entry_section(
    label: str,
    identifier: str,
    image_url: str,
    alt: str,
    title: str,
    lines: list[str],
) -> str:
    section = [f"### {label}", "<!-- Auto-generated entry. Add a description above the image if you want. -->"]
    section.extend(lines)
    section.append(f'![{alt}]({image_url} "{title}")')
    return "\n".join(section).rstrip() + "\n"


def split_catalog(text: str) -> tuple[str, list[dict[str, str]], int | None]:
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return text.rstrip() + "\n", [], None
    prefix = text[: matches[0].start()]
    sections: list[dict[str, str]] = []
    placeholder_index: int | None = None
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        raw = text[match.start() : end]
        title = match.group(1).strip()
        if title in PLACEHOLDER_TITLES:
            placeholder_index = len(sections)
        sections.append({"title": title, "raw": raw.strip() + "\n"})
    return prefix, sections, placeholder_index


def existing_names(sections: list[dict[str, str]], aliases: dict[str, list[str]]) -> set[str]:
    names: set[str] = set()
    for section in sections:
        if section["title"] in PLACEHOLDER_TITLES:
            continue
        names.add(normalize(section["title"]))
    for values in aliases.values():
        for value in values:
            names.add(normalize(value))
    return names


def heading_matches(name: str, candidates: set[str]) -> bool:
    if name in candidates:
        return True
    return any(name.startswith(candidate + " (") or name.startswith(candidate + " - ") for candidate in candidates if candidate)


def update_catalog(
    page: Path,
    new_sections: list[tuple[str, str]],
    aliases: dict[str, list[str]],
    dry_run: bool,
) -> int:
    with page.open("r", encoding="utf-8", newline="") as handle:
        original = handle.read()
    crlf = "\r\n" in original
    text = original.replace("\r\n", "\n")
    _, sections, placeholder_index = split_catalog(text)
    names = existing_names(sections, aliases)
    accepted: list[tuple[str, str]] = []
    for label, section in new_sections:
        normalized = normalize(label)
        if heading_matches(normalized, names):
            continue
        names.add(normalized)
        accepted.append((label, section))
    if not accepted:
        return 0
    accepted.sort(key=lambda item: item[0].casefold())
    rendered = "\n".join(section.strip() + "\n" for _, section in accepted)

    # Insert into the original text instead of re-rendering existing sections,
    # so hand-written entries keep their exact formatting.
    matches = list(HEADING_RE.finditer(text))
    if placeholder_index is not None and placeholder_index < len(matches):
        insert_at = matches[placeholder_index].start()
        prefix_text = text[:insert_at]
        if prefix_text.endswith("\n\n"):
            separator = ""
        elif prefix_text.endswith("\n"):
            separator = "\n"
        else:
            separator = "\n\n"
        new_text = prefix_text + separator + rendered + "\n" + text[insert_at:]
    else:
        new_text = text.rstrip() + "\n\n" + rendered
        if not new_text.endswith("\n"):
            new_text += "\n"

    if not dry_run:
        if crlf:
            new_text = new_text.replace("\n", "\r\n")
        with page.open("w", encoding="utf-8", newline="") as handle:
            handle.write(new_text)
    return len(accepted)


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Add missing blocks/items to the Sculk Depths wiki catalogs.")
    parser.add_argument("--config", type=Path, default=None, help="Path to catalog.config.json")
    parser.add_argument("--wiki-repo", help="Path to the Sculk-Depths wiki repository")
    parser.add_argument("--mod-repo", help="Path to the Sculk-Depths mod repository")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing files")
    parser.add_argument("--force-images", action="store_true", help="Re-render images even if the manifest says they are current")
    parser.add_argument("--all-images", action="store_true", help="Also render images for entries that already exist")
    parser.add_argument("--limit", type=int, default=0, help="Only add the first N missing entries")
    parser.add_argument("--only", choices=("blocks", "items"), help="Only update one catalog")
    parser.add_argument("--resolution", help="Image preset/size: 720p, 1080p, or 1280x720")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    # Resolve the config first. When --wiki-repo is supplied without --config,
    # prefer that repository's own tools/catalog.config.json.
    explicit_wiki = args.wiki_repo or os.environ.get("SCULK_DEPTHS_WIKI_DIR")
    if args.config:
        config_path = args.config
    elif explicit_wiki:
        candidate = Path(explicit_wiki).expanduser().resolve() / "tools" / "catalog.config.json"
        config_path = candidate if candidate.exists() else DEFAULT_CONFIG_PATH
    else:
        config_path = DEFAULT_CONFIG_PATH

    config = load_config(config_path)
    wiki_root = resolve_wiki_root(args.wiki_repo, config)
    config["_wikiRoot"] = wiki_root
    resolve_image_config(config, args)
    mod_repo = find_mod_repo(args.mod_repo, config, wiki_root)
    config["_modRepo"] = mod_repo
    if not args.quiet:
        print(f"Wiki repo: {wiki_root}")
        print(f"Mod repo: {mod_repo}")
        print(f"Image size: {config['images']['width']}x{config['images']['height']}")

    lang = load_lang(mod_repo / "src/main/resources/assets/sculk_depths/lang/en_us.json")
    block_registrations, constants = scan_registrations(
        mod_repo / "src/main/java/net/ugi/sculk_depths/block/ModBlocks.java"
    )
    item_registrations, _ = scan_registrations(
        mod_repo / "src/main/java/net/ugi/sculk_depths/item/ModItems.java"
    )
    excluded_blocks = set(config.get("exclude", {}).get("blocks", []))
    excluded_items = set(config.get("exclude", {}).get("items", []))
    blocks = {
        identifier: entry
        for identifier, entry in block_registrations.items()
        if entry.get("kind") == "Block" and identifier not in excluded_blocks
    }
    items = {
        identifier: entry
        for identifier, entry in item_registrations.items()
        if entry.get("kind") == "Item" and identifier not in excluded_items
    }
    tools, tiers = load_tool_data(mod_repo)
    spawn_egg_tints = load_spawn_egg_tints(mod_repo)
    store = TextureStore(mod_repo)
    manifest_path = wiki_root / config.get("manifest", "static/.catalog-manifest.json")
    manifest = load_manifest(manifest_path)
    property_cache: dict[str, dict[str, Any]] = {}
    rendered = skipped_images = 0
    total_added = 0

    catalogs = config.get("catalogs", {})
    for name, catalog in catalogs.items():
        if args.only and name != args.only:
            continue
        page = wiki_root / catalog["page"]
        if not page.exists():
            if not args.quiet:
                print(f"Skipping {name}: page not found ({page})")
            continue
        text = page.read_text(encoding="utf-8")
        _, sections, _ = split_catalog(text.replace("\r\n", "\n"))
        aliases = {
            identifier: cfg.get("aliases", [])
            for identifier, cfg in (config.get(name, {}) or {}).items()
            if isinstance(cfg, dict) and cfg.get("aliases")
        }
        existing = existing_names(sections, aliases)
        source = catalog.get("source", name)
        image_dir = wiki_root / catalog["imageDir"]
        url_prefix = catalog["urlPrefix"].rstrip("/")
        candidates: list[dict[str, Any]] = []
        missing: list[str] = []
        labels_seen: dict[str, int] = {}
        remaining = args.limit if args.limit else None
        entries = blocks if source == "blocks" else items
        for identifier, entry in sorted(entries.items()):
            entry_config = config.get(name, {}).get(identifier, {}) or {}
            if entry_config.get("exclude"):
                continue
            label = entry_config.get("label") or display_name(
                identifier, lang, "item" if source == "items" else "block"
            )
            key = normalize(label)
            labels_seen[key] = labels_seen.get(key, 0) + 1
            if labels_seen[key] > 1:
                label = f"{label} ({titleize(identifier)})"
                key = normalize(label)
            is_new = not heading_matches(key, existing)
            candidates.append(
                {
                    "identifier": identifier,
                    "entry": entry,
                    "label": label,
                    "is_new": is_new,
                    "image_path": image_dir / f"{identifier}.png",
                    "image_url": f"{url_prefix}/{identifier}.png",
                    "alt": catalog["alt"].format(label=label, id=identifier),
                    "title": catalog["title"].format(label=label, id=identifier),
                }
            )
            if is_new:
                missing.append(label)
                if remaining is not None and len(missing) >= remaining:
                    break

        new_sections: list[tuple[str, str]] = []
        for candidate in candidates:
            identifier = candidate["identifier"]
            label = candidate["label"]
            if source == "blocks":
                visual = build_block_visual(store, identifier, label, config)
                lines = (
                    property_lines(
                        identifier,
                        candidate["entry"],
                        config,
                        block_registrations,
                        constants,
                        property_cache,
                        tools,
                        tiers,
                        lang,
                    )
                    if catalog.get("includeProperties", True)
                    else []
                )
            else:
                visual = build_item_visual(store, identifier, label, config, spawn_egg_tints)
                lines = []
            if candidate["is_new"]:
                new_sections.append(
                    (
                        label,
                        entry_section(
                            label,
                            identifier,
                            candidate["image_url"],
                            candidate["alt"],
                            candidate["title"],
                            lines,
                        ),
                    )
                )
            image_path = candidate["image_path"]
            digest = visual_hash(visual, config["images"])
            manifest_entry = manifest.get(f"{name}/{identifier}", {})
            force = args.force_images or (args.all_images and not candidate["is_new"])
            if (
                not force
                and image_path.exists()
                and manifest_entry.get("hash") == digest
                and manifest_entry.get("width") == config["images"]["width"]
                and manifest_entry.get("height") == config["images"]["height"]
            ):
                skipped_images += 1
                continue
            if args.dry_run:
                continue
            image = render_visual(visual, config["images"], store)
            save_image(
                image,
                image_path,
                label,
                "item" if source == "items" else "block",
                config["images"],
            )
            manifest[f"{name}/{identifier}"] = {
                "hash": digest,
                "image": str(image_path.relative_to(wiki_root)).replace("\\", "/"),
                "width": config["images"]["width"],
                "height": config["images"]["height"],
            }
            rendered += 1

        added = update_catalog(page, new_sections, aliases, args.dry_run)
        total_added += added
        if not args.quiet:
            print(
                f"{name}: {len(entries)} registered, {len(sections)} existing sections, "
                f"{len(missing)} missing, {added} added"
            )

    if not args.dry_run and (rendered or manifest):
        save_manifest(manifest_path, manifest)
    if not args.quiet:
        print(f"Images rendered: {rendered}, unchanged/skipped: {skipped_images}")
        print(f"Entries added: {total_added}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
