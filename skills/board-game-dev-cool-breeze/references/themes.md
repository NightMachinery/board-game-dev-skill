# Themes and art direction

A **theme** is one complete look: an art direction, the UI colour tokens, and the art assets drawn
in that direction. A game ships one theme at first and can add more later, each changing the look
of the whole game, without copying assets between them.

## The kickoff conversation

At the start of a game, before any art is produced, propose three to five themes and let the owner
choose one. For each candidate, give:

- its mood and idiom in a sentence (for example "a Safavid manuscript page: flat perspective, ink
  outlines, jewel-tone gouache");
- the palette as named hues, and whether the theme is **light** or **dark**;
- how it reads at thumbnail size on a phone, since card art is mostly seen small;
- what it costs: how many bitmap kinds it needs, and how hard the idiom is for the image model
  (some idioms invite pseudo-writing or clutter that every image must be checked for);
- how far it sits from the look of any published edition, which matters for originality.

Always include the bundled themes in this directory that fit the setting, and add fresh ones drawn
from the game's world. Parody, pastiche and deconstruction are all legitimate directions. Record
the choice in the decisions file.

## The contract

```
themes/<id>/theme.json
themes/<id>/style.md            # the art direction: look, palette, motifs, do, don't, kind templates, style prefix
themes/<id>/subjects.json       # optional: per-theme subject overrides
```

`theme.json`:

```json
{
  "id": "my-theme-night",
  "name": "My theme, night",
  "mode": "dark",
  "inherits": ["my-theme"],
  "artDirection": "style.md",
  "tokens": { "table": "oklch(0.22 0.06 262)", "fg": "oklch(0.94 0.02 85)" }
}
```

- `mode` is required and is `light` or `dark`. It sets the page's `color-scheme` and tells
  reviewers which contrast pairs to check.
- `inherits` lists parent themes in precedence order. Tokens and assets missing from a theme are
  taken from its parents, in that order.
- `tokens` are the semantic UI tokens (surfaces, text, rules, accent, focus, the game's own
  colour families). Components use only semantic tokens, never a raw colour, so a theme can change
  everything.

In the project:

- the subjects (what each card, token or board piece depicts) belong to the **game**, in
  `art/subjects.json`; a theme may override some with its own `subjects.json`;
- each theme has a progress manifest, `art/manifests/<theme>.json`, listing what is generated,
  approved or rejected;
- approved originals live at `art/originals/<theme>/<kind>/<slug>.webp` (lossless), shipped files
  at `web/static/art/<theme>/`, and the generated availability index at
  `web/src/lib/art/<theme>.gen.json`;
- the project config names `themes_dir`, `default_theme` and the art kinds with their sizes and
  byte budgets (`templates/tools/project.json`).

**Resolution**: for each asset, the client takes the theme's own approved file, then each parent's
in order, then a deliberate procedural placeholder. There are no broken images, and a new theme can
start as an empty child of an existing one and replace assets one at a time.

## Light and dark

A dark look is its own theme, usually a child of the light one. Changing only the UI tokens is not
enough when the art itself is light: cards painted on ivory paper still glow on a dark table. A
real dark theme repaints the assets whose ground is light (card art, backs, textures) or gives them
a darker ground, and checks every contrast pair again. Plan for that work when choosing a dark
theme; do not ship a dark mode that only recolours the chrome.

## Bundled themes

- [persian-safavid-illuminated-garden](../themes/persian-safavid-illuminated-garden/style.md)
  (light): a Safavid manuscript page. Flat decorative perspective, fine ink outlines, opaque gouache
  in jewel tones (lapis, turquoise, saffron, vermilion, malachite, ochre), gold leaf only as small
  accents, an ivory paper ground, cypresses, pastel hills, girih tilework and ornamental clouds.
- [persian-safavid-illuminated-garden-night](../themes/persian-safavid-illuminated-garden-night/style.md)
  (dark, inherits the garden): the same idiom on a lapis night ground, gold as the accent. Its UI
  tokens are proven; its art is a plan, because the parent's paper-ground art must be repainted for
  the night ground.

To add a bundled theme, give it a `theme.json` in this shape and a `style.md` with no game-specific
subjects.
