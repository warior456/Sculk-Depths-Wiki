# Wiki catalog tool

`tools/catalog_tool.py` keeps the block and item catalogs in sync with the
Sculk Depths mod. It only **adds** missing `###` sections, so hand-written
descriptions, recipes and screenshots are never overwritten.

For every new entry it:

- reads the display name from `en_us.json`;
- extracts hardness, blast resistance, required tool/tier and loot drops from
  the mod source and generated data;
- renders a 1280x720 preview from the mod's own models and textures;
- writes descriptive `alt`/`title` text and PNG metadata for search engines;
- records the image hash in `static/.catalog-manifest.json` so unchanged images
  are skipped on later runs.

## Quick start

```powershell
python -m pip install -r tools/requirements.txt
python tools/catalog_tool.py
```

Useful flags:

```powershell
python tools/catalog_tool.py --dry-run              # show what would change
python tools/catalog_tool.py --limit 5              # only first 5 new entries
python tools/catalog_tool.py --only blocks          # one catalog only
python tools/catalog_tool.py --force-images         # re-render every image
python tools/catalog_tool.py --all-images           # re-render existing entries
python tools/catalog_tool.py --resolution 1080p     # 720p, 1080p, 1440p, 2160p
python tools/catalog_tool.py --width 1600 --height 900
```

## Repository locations

Both repositories are configurable. Resolution order is:

| Setting | Wiki repo | Mod repo |
| --- | --- | --- |
| CLI flag | `--wiki-repo` | `--mod-repo` |
| Environment variable | `SCULK_DEPTHS_WIKI_DIR` | `SCULK_DEPTHS_DIR` |
| Config key | `wikiRepo` | `modRepo` |
| Fallback | repository containing this script | common local paths, `.mod-sources`, sibling folders |

Examples:

```powershell
python tools/catalog_tool.py `
  --wiki-repo C:\Users\me\programmeren\Sculk-Depths-Wiki `
  --mod-repo C:\Users\me\IdeaProjects\Sculk-Depths
```

If `--wiki-repo` is supplied without `--config`, the tool loads
`<wiki-repo>/tools/catalog.config.json`.

## Configuration

Edit `tools/catalog.config.json`:

```jsonc
{
  "wikiRepo": null,          // optional absolute/relative path
  "modRepo": null,           // optional absolute/relative path
  "images": {
    "width": 1280,
    "height": 720,
    "fill": 0.66,            // block fills 66% of the frame
    "itemFill": 0.45,        // item fills 45% of the frame
    "verticalOffset": 12,
    "background": { "top": "#d4d7da", "bottom": "#eef0f2", "vignette": 0.12 },
    "shadow": { "enabled": true, "opacity": 105, "blur": 26, "spread": 1.06 },
    "textureFilter": "nearest",
    "compressLevel": 6
  },
  "blocks": {
    "flumrock_cauldron": { "render": "model" },
    "sculk_pedestal": { "render": "model" },
    "my_block": {
      "render": "auto",                         // auto | model | formation
      "formation": "stairs",                    // force a fallback shape
      "model": "sculk_depths:block/my_model",   // force a model
      "textures": { "side": "sculk_depths:block/my_texture" },
      "label": "Custom Display Name",
      "aliases": ["Old Display Name"],
      "exclude": false
    }
  },
  "items": {
    "my_item": {
      "model": "sculk_depths:item/my_item",
      "texture": "sculk_depths:item/my_item_texture",
      "label": "Custom Display Name",
      "exclude": false
    }
  },
  "formationRules": [
    { "suffix": "_stairs", "formation": "stairs" },
    { "suffix": "_slab", "formation": "slab" }
  ],
  "formations": {
    "my_shape": {
      "boxes": [
        { "from": [0, 0, 0], "to": [16, 8, 16] }
      ]
    }
  },
  "exclude": { "blocks": [], "items": [] }
}
```

### How a block is rendered

1. If `render` is `model`, or `auto` and the block model has `elements`, the
   mod model is rendered directly.
2. Otherwise a fallback formation is used. `formationRules` maps name suffixes
   such as `_stairs`, `_slab`, `_wall`, `_fence`, `_door`, `_sign` and `_sapling`
   to shapes. You can force a shape per block with `"formation": "..."`.
3. Vanilla cross models (flowers, saplings, sprouts) are fitted to the visible
   sprite so small plants still fill the preview.
4. Animated textures are sampled from their first frame.
5. Fences and walls use their inventory model so the preview shows the full
   shape instead of only the post.

Formation boxes use Minecraft model units (`0..16`). Add your own shape under
`formations` and reference it by name.

### How items are rendered

Item models are resolved from `assets/sculk_depths/models/item`. Layered models
(`layer0`, `layer1`, ...) are composited. Spawn eggs use the vanilla egg texture
tinted with the primary/secondary colors from `SpawnEggItem` in `ModItems.java`.
If a model cannot be found, the tool falls back to
`sculk_depths:item/<id>`, then `sculk_depths:block/<id>`.

## What the tool will not do

- It never rewrites an existing `###` section.
- It never changes manual entries such as `Flumrock Cauldron`,
  `Kryslum Enriched Soil`, `Quazarith Ore` or `Energy Essence`.
- It does not add descriptions to new entries; the generated marker
  `<!-- Auto-generated entry... -->` is intentionally left so a human can add
  context above the image.

## Automation

`.github/workflows/update-catalog.yml` runs on a schedule, on demand, and when
the tool itself changes:

1. checks out this wiki repository;
2. checks out the public `warior456/Sculk-Depths` repository into `.mod-sources`
   (the default `GITHUB_TOKEN` can read public repositories, so no extra secret
   is needed);
3. installs Java 21 and runs `./gradlew createMinecraftArtifacts` to download
   the vanilla client resources used for parent models and textures;
4. fails the job if the `client-extra` jar is missing, so degraded previews are
   never committed;
5. installs Pillow and runs
   `python tools/catalog_tool.py --wiki-repo . --mod-repo .mod-sources`;
6. commits new entries/images if anything changed and dispatches the Retype
   publish workflow.

The workflow needs `contents: write` and `actions: write`.

The source repository and ref are configurable without editing the workflow:

| Setting | Repository variable | Manual input |
| --- | --- | --- |
| Mod repository | `MOD_REPOSITORY` (default `warior456/Sculk-Depths`) | — |
| Mod ref | `MOD_REF` (default `portal-neoforge`) | `mod_ref` |

Pushes made with `GITHUB_TOKEN` do not trigger other workflows, so the workflow
calls `gh workflow run retype-action.yml` explicitly.

## SEO notes

- Catalog pages have `meta.title`, `meta.description` and an `image` in their
  frontmatter.
- Every generated image has descriptive `alt` and `title` text plus PNG
  `Title`, `Description` and `Keywords` metadata.
- `retype.yml` sets the site name, description and social image.
- Keep the auto-generated marker in place: it makes it clear which sections are
  safe for the tool to maintain.

## Known limitations

- Properties declared inside helper methods (for example
  `ModBlocks.createCrystalBlock`) are not parsed yet; those blocks get an image
  and drops but may omit hardness.
- Only item/block models and the fallback formations are rendered; custom
  block-entity renderers are not executed.
- The tool reads the mod's `en_us.json` with a small regex parser because the
  file contains `//` comments and is not valid JSON.
