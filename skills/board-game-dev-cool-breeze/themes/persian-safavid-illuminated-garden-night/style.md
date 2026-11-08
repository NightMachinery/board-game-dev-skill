# Art direction: Persian Safavid illuminated garden, night

A dark theme that inherits [the illuminated garden](../persian-safavid-illuminated-garden/style.md):
the same idiom, palette names, motifs, rules and kind templates, moved onto a lapis night ground
with gold as the accent. Read the parent first; this file lists only what changes.

**Status.** The UI tokens are proven: they shipped as a dark mode and passed the same contrast
checks as the parent. The art is a plan. A game that used the parent's art under these tokens found
that ivory-paper cards still glowed on the dark table, so the night theme needs its own art for
every asset with a light ground, and its card surface tokens (`card-paper`, `card-ink`) are
proposals until that art exists and the contrast pairs are checked again.

## What changes

- **Ground.** Deep lapis paper instead of ivory, with faint lighter fibres. Every "ivory paper" in
  the parent's prefix and kind templates becomes "deep lapis night paper".
- **Gold.** Still leaf accents only, but brighter against the night; it is also the UI accent and
  focus colour.
- **Light.** Moonlight and lamplight: cool highlights on the subject, warm small light sources
  (lamps, a lit window, stars as small gold points). No dramatic chiaroscuro; the idiom stays flat.
- **Palette.** The jewel tones stay, a step lighter where they sit directly on the night ground so
  they keep 3:1 against it.
- **Assets to repaint.** Card art, board art, backs, textures, avatars and victory scenes: anything
  that fades to paper. Tokens keep their own flat accent ground inside the rim; only the paper
  margin around the rim changes.

## Style prefix (verbatim)

> Original illustration in the manner of a 16th-century Persian miniature painting (Safavid
> manuscript illumination), set at night: flat decorative perspective, fine pale-gold ink outlines,
> opaque gouache in jewel tones (lapis lazuli blue, turquoise, saffron, vermilion, malachite green,
> ochre) slightly lightened for a dark ground, with small touches of bright gold leaf; stylized
> cypress trees, rounded rocky hills with moonlit pastel edges, patterned tilework, ornamental
> clouds, tiny figures in period dress, small warm lamps and gold star points. The sky and
> background are plain deep lapis night paper, never gold leaf; gold appears only on small details
> such as finials, rims, stars and a moon disc. Robes are plain or patterned with small rosettes or
> leafy sprigs. One clear central subject readable as a small thumbnail, calm uncluttered
> background of deep lapis paper. No inscriptions, no glyph friezes, no writing on scrolls, pages,
> banners, cloth or buildings; scrolls and pages are blank, cloth shows only plain stripes or small
> floral sprigs, and parapets show only plain geometric tile bands. No border, no frame, no
> watermark, no signature. Not photorealistic, not 3D, no modern objects.

## UI

A lapis night table with the night paper texture, slightly lighter lapis panels, ivory text, gold
accent and focus rings. Cards take a dark lapis surface with ivory ink once their art is repainted.
