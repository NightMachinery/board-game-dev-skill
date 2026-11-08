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

## Kind templates

The parent's kinds with the night ground. A token keeps its flat accent ground inside the rim; only the paper around it changes.

- **card**: "{subject}. Landscape vignette, subject centred, dominant accent {accent}. Keep every figure and object inside the central area; leave a wide margin of plain deep lapis night paper on all four sides, widest at left and right. One or two large figures doing the named activity, filling the central third; no crowds, no distant skyline, no filler animals unless the subject names them. No building in the background unless the subject names one. Soft vignette fading to the night paper colour at the edges."
- **board**: "Panoramic view of {subject} as monumental architecture in the Persian-miniature idiom, landscape, dominant accent {accent}. The monument centred and whole, occupying the middle third, not cut by the frame. Soft vignette fading to the night paper colour at the edges." (a large location or monument)
- **token**: "Circular medallion centred on a square of plain deep lapis night paper, filling the square except for a narrow, even margin of paper (about 4 percent of the width) on every side; the paper outside the rim is flat and clean, with no vignette, fade, shadow or ornament. Inside: a flat {accent} ground, one bold symmetric emblem of {subject} filling the central 60 percent, a thin crisp bright gold rim only; no landscape, trees, rocks, ground or clouds inside the medallion; no ornamental border band."
- **back**: "Symmetric ornamental illumination (tazhib, girih strapwork), portrait orientation, no figures: {subject}. Soft vignette fading to the night paper colour at the edges."
- **texture**: "Seamless fine deep lapis paper grain with faint lighter fibres, {subject}, no figures, no objects, suitable for tiling."
- **hero**: "Wide panoramic scene: {subject}, landscape, moonlight with small warm lamps, dominant accent {accent}. Soft vignette fading to the night paper colour at the edges."
- **avatar**: "Portrait bust, shoulders up, one figure, centred: {subject}. Dominant accent {accent}, plain deep lapis background, no scenery. Soft vignette fading to the night paper colour at the edges."
- **victory**: "Wide celebratory scene: {subject}, landscape, dominant accent {accent}. Soft vignette fading to the night paper colour at the edges."
- **icon**: "Simple bold emblem on a plain deep lapis ground, readable at 32 pixels: {subject}. Dominant accent {accent}, no scenery, no background detail. Soft vignette fading to the night paper colour at the edges." (the app icon)

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
