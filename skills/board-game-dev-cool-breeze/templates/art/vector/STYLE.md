# Vector direction skeleton

Define a coherent icon grammar: viewBox, optical grid, strokes, corner rules,
negative space, palette roles, and the smallest supported size. Icons carry
game information and must read at their actual display size without colour.

- Hand-author local SVG. Keep shapes editable and text out of the artwork.
  Render labels as translated HTML/SVG text in the component.
- Use semantic theme colours with `currentColor` fallbacks. Make each inline
  icon's gradient/mask/clip ids unique. No external references or shared sprite.
- Render at small and large sizes on the active theme background. Use
  `tools/art/render-fast.sh in.svg SIZE out.png [background] [ink]` for the
  inner loop, then check the finished batch with `tools/chrome/svg-render.mjs`.
- Inspect every render, fix muddy silhouettes, inconsistent weight and clipping,
  then render again. Keep short design briefs and review logs outside shipped assets.
- Test glyphs in greyscale and colour-deficiency emulation. Distinguish states
  with shape/labels as well as hue. One active theme determines all tokens.
