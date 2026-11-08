# Art direction: Persian Safavid illuminated garden

A light theme. The game looks like a page from a 16th-century Safavid illustrated manuscript: an
ivory page, jewel-tone gouache, ink outlines and small touches of gold. It was proven on a full set
of cards, tokens, backs, textures, avatars and victory scenes for a card-drafting game, and its UI
tokens passed contrast checks (4.5:1 for text pairs, 3:1 for control borders).

The bitmap pipeline builds every prompt as: the **style prefix** below, then the **kind template**
for the asset's kind, then the asset's `subject` from the game's `art/subjects.json`, then any
amendment a review round added. Nothing else goes into a prompt.

## Look

Persian-miniature illustration in the Safavid manuscript idiom: flat decorative perspective with no
vanishing-point realism, fine dark ink outlines, opaque gouache in jewel tones and small touches of
gold leaf. One clear central subject that stays readable as a small thumbnail, on a calm,
uncluttered ground of warm ivory paper. Most kinds fade into the paper with a soft vignette; a
token sits on flat paper inside a crisp rim; a texture runs evenly to every edge so it tiles.

## Palette

Named hues, so every prompt and every reviewer uses the same words. They match the theme's OKLCH
tokens in `theme.json`, so a painted scene and its UI frame read as one object.

- **lapis**: deep blue; night sky, water, the UI accent
- **turquoise**: cool green-blue
- **saffron**: warm yellow-orange; commerce, sunlight
- **vermilion**: warm red; conflict, fire
- **malachite**: green; growth, learning
- **ochre**: warm earth brown; raw materials, ground
- **violet**: used sparingly, for a rare category
- **amber**: honey-brown; wood, tools, stonework
- **rose**: soft pink-red, calmer than vermilion
- **slate**: cool blue-grey; stone, technical and civic subjects
- **gold**: leaf accents only (a robe's border, a finial, a coin, a sun disc). Never a flat fill,
  a sky or a background: gold is a highlight, not a ground.
- **ivory**: the paper ground everything sits on

Give each game category or player one dominant accent from this list, and pair every colour with a
shape or pattern, since colour alone fails for colour-blind players.

## Motifs

Stylized cypress trees; rounded rocky hills with pastel edges; girih strapwork tile patterns;
ornamental Chinese-cloud scrolls; tiny figures in period dress at the flattened three-quarter angle
of the idiom; domes, arches and columns; calm water as a patterned ripple, not a reflection. A
scene shows a background building only when its subject names one.

## Do

- One clear subject, centred, readable at a glance at its smallest display size.
- Flat decorative perspective: figures and buildings stack by composition.
- Fine, continuous ink outlines around every shape.
- Opaque colour fields, not watercolour washes or airbrushed gradients.
- A warm ivory ground the subject sits on, not a hard rectangle behind it.

## Don't

- **Realism, photorealism or 3D rendering.** The flat idiom is the theme's identity, and it keeps
  the art distinct from photographed or painterly published editions.
- **Writing of any kind in the image**: no text, letters, numerals, calligraphy, pseudo-writing,
  inscriptions, glyph friezes or signatures. Scrolls and pages are blank; cloth carries stripes,
  checks or small floral sprigs; parapets, door panels and steps carry plain geometric tile bands.
  This idiom invites pseudo-script on buildings and cloth, and it shows only at full resolution, so
  inspect every image at full size as well as at thumbnail size. Numbers and labels are drawn by
  the client over the art, never painted in.
- **A frame, border or watermark.** The processing step feathers the image into the card.
- **Filler animals or repeated motifs** unless the subject names them; a peacock on every card makes
  a set look repetitive.
- **Anachronisms**: nothing that reads as a specific modern object, uniform or technology.
- **Any likeness of a published game's art, card frames or iconography.**

## Kind templates

`{subject}` and `{accent}` come from the asset's subject entry. Edge treatment lives here, not in
the prefix, because the kinds disagree about it.

- **card**: "{subject}. Landscape vignette, subject centred, dominant accent {accent}. Keep every figure and object inside the central area; leave a wide margin of plain ivory paper on all four sides, widest at left and right. One or two large figures doing the named activity, filling the central third; no crowds, no distant skyline, no filler animals unless the subject names them. No building in the background unless the subject names one. Soft vignette fading to the paper colour at the edges."
- **board**: "Panoramic view of {subject} as monumental architecture in the Persian-miniature idiom, landscape, dominant accent {accent}. The monument centred and whole, occupying the middle third, not cut by the frame. Soft vignette fading to the paper colour at the edges." (a large location or monument)
- **token**: "Circular medallion centred on a square of plain ivory paper, filling the square except for a narrow, even margin of paper (about 4 percent of the width) on every side; the paper outside the rim is flat and clean, with no vignette, fade, shadow or ornament. Inside: a flat {accent} ground, one bold symmetric emblem of {subject} filling the central 60 percent, a thin crisp gold rim only; no landscape, trees, rocks, ground or clouds inside the medallion; no ornamental border band."
- **back**: "Symmetric ornamental illumination (tazhib, girih strapwork), portrait orientation, no figures: {subject}. Soft vignette fading to the paper colour at the edges."
- **texture**: "Seamless fine paper grain, {subject}, no figures, no objects, suitable for tiling."
- **hero**: "Wide panoramic scene: {subject}, landscape, warm inviting light, dominant accent {accent}. Soft vignette fading to the paper colour at the edges."
- **avatar**: "Portrait bust, shoulders up, one figure, centred: {subject}. Dominant accent {accent}, plain ivory background, no scenery. Soft vignette fading to the paper colour at the edges."
- **victory**: "Wide celebratory scene: {subject}, landscape, dominant accent {accent}. Soft vignette fading to the paper colour at the edges."
- **icon**: "Simple bold emblem on a plain ivory ground, readable at 32 pixels: {subject}. Dominant accent {accent}, no scenery, no background detail. Soft vignette fading to the paper colour at the edges." (the app icon)

## Style prefix (verbatim)

> Original illustration in the manner of a 16th-century Persian miniature painting (Safavid
> manuscript illumination): flat decorative perspective, fine dark ink outlines, opaque gouache in
> jewel tones (lapis lazuli blue, turquoise, saffron, vermilion, malachite green, ochre) with small
> touches of gold leaf; stylized cypress trees, rounded rocky hills with pastel edges, patterned
> tilework, ornamental clouds, tiny figures in period dress. The sky and background are plain ivory
> paper, never gold leaf; gold appears only on small details such as finials, rims and a sun disc.
> Robes are plain or patterned with small rosettes or leafy sprigs. One clear central subject
> readable as a small thumbnail, calm uncluttered background of warm ivory paper. No inscriptions,
> no glyph friezes, no writing on scrolls, pages, banners, cloth or buildings; scrolls and pages are
> blank, cloth shows only plain stripes or small floral sprigs, and parapets show only plain
> geometric tile bands. No border, no frame, no watermark, no signature. Not photorealistic, not
> 3D, no modern objects.

## UI

The interface is the manuscript page: an ivory table with a faint paper-grain texture, brighter
panels, ink text, lapis as the accent and deep gold for gilded rules. Headings and card names in
Fraunces 600, the UI in Inter with tabular figures (both OFL; self-host them). Cards are
paper-coloured.
