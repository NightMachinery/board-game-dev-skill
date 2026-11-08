# Art and sound

Two pipelines, matched to what each asset needs, under one theme ([themes.md](themes.md)).

- **Vectors** (icons, symbols, frames, badges, the logo) are hand-authored SVG drawn by a strong
  model in a render, look, critique loop: a fast rasterizer for each iteration
  (`templates/tools/art/render-fast.sh`), the headless browser once per batch for fidelity
  (`templates/tools/chrome/svg-render.mjs`). Rules for drawing live in `art/vector/STYLE.md`,
  per-set specs in `art/vector/specs/`, iteration logs in `art/vector/log/`.
- **Bitmaps** (card, board and token art, backs, textures) come from an image model, strictly one at
  a time through the guard's `codex` lane (`templates/tools/art/generate.mjs`). Every prompt is the
  theme's style prefix, then the kind template, then the subject, then any amendment from review.
- **Originals** are committed losslessly (WebP, pixel-identical to the generated PNG); **shipped**
  files are derived AVIF with content hashes and per-size byte budgets; the app references only
  approved art through a generated index and draws placeholders for the rest.
- **Sound** comes from verified CC0 or compatible sources with provenance, is trimmed and normalized
  once, ships as small compressed files loaded after the first gesture, and keeps a synthesized
  fallback.

## Lessons

Each lesson is a rule and its reason. The label says how strong the evidence was: *seen once* (one concrete finding), *seen repeatedly* (recurring failures or independent checks across subsystems), or *owner decision* (an accepted preference, which a new owner may change).

- **8.01** Split vectors and bitmaps into different production pipelines matched to their needs. Editable small SVG symbols benefit from drawing and visual critique, while illustrated scenes benefit from image generation. *(owner decision)*

- **8.02** Create an asset manifest, stable ids, subject briefs and a shared art direction before bulk production. Generated art drifts less when every prompt combines a common style, a kind template and a specific subject. *(seen repeatedly)*

- **8.03** Prove a small pilot through generation, critique, cropping, encoding and real UI placement before scaling. Attractive raw samples did not alone establish that a whole asset kind would ship correctly. *(seen repeatedly)*

- **8.04** Generate bitmap assets one at a time through a shared resource lane. Sequential production limits resource contention and makes approval, retries and provenance easier to track. *(owner decision)*

- **8.05** Keep approved originals losslessly in version control and verify decoded pixels during conversion. Regenerate delivery formats from the original rather than progressively recompressing shipped files. *(seen repeatedly)*

- **8.06** Ship responsive compressed variants with generated content hashes and per-variant budgets. Choose resolution from measured display size and device pixel ratio, bounded by the original's useful detail. *(seen repeatedly)*

- **8.07** Budget what a screen and prefetch plan transfer rather than imposing a blanket cap on the entire art collection. Not every asset loads at once, but totals and plan bytes should still be reported. *(owner decision)*

- **8.08** Inspect every generated picture at full resolution and at its actual thumbnail size. Pseudo-writing hid on buildings and cloth at full size, while muddled silhouettes appeared only after reduction. *(seen repeatedly)*

- **8.09** Keep game numbers, localized text, costs and live effects outside paintings. Code-rendered overlays stay translatable and correct when rules or layout change. *(seen repeatedly)*

- **8.10** Give asset kinds their own crop, margin, edge and masking rules. A vignette suitable for a card can damage a crisp token rim or make a texture impossible to tile. *(seen repeatedly)*

- **8.11** Draw icons at their smallest actual use size and simplify geometry before thinning features. Scaling a detailed large drawing down can erase gaps and merge important symbols. *(seen repeatedly)*

- **8.12** Iterate vectors through lint, fast raster rendering, direct visual inspection and a browser specimen in real contexts. Fast renderers save time, but browser fidelity and inherited colors still need verification. *(seen repeatedly)*

- **8.13** Test symbol recognition in grayscale, color-vision emulations and relevant surfaces, including supported themes. Meaning should survive without a secondary tone or a particular hue. *(seen repeatedly)*

- **8.14** Use fresh readers and hidden answer keys for blind identification, then compare the whole icon family for consistency. A designer remembering their own labels cannot supply independent recognition evidence. *(seen repeatedly)*

- **8.15** Keep visual specs explicit about “must not be confused with” meanings and cap unsuccessful iterations. This targets real semantic ambiguity while preventing an endless polishing loop. *(seen repeatedly)*

- **8.16** Namespace new-game assets and reuse approved art through explicit bindings rather than copies or name matching. This protects old hashes and prevents a shared name from implying a misleading illustration. *(seen repeatedly)*

- **8.17** Build card backs and art prefetch plans only from public categories and catalogs. Asset selection and request timing can reveal a hidden deal even when the JSON view is redacted. *(seen repeatedly)*

- **8.18** Source sound under a verified compatible license and retain originals, source hashes, license evidence and transformation metadata. “Free download” is not an adequate provenance record. *(seen repeatedly)*

- **8.19** Audition prepared cues, normalize and trim them consistently, then inspect the decoded delivery output. Encoding changes peaks and timing, and numerical audio statistics cannot replace listening. *(seen repeatedly)*

- **8.20** Unlock audio on a user gesture, load files lazily, bound overlapping voices and retain a synthesized fallback. Sound loading must neither delay play nor replay an event that already passed. *(seen repeatedly)*

- **8.21** Reference only approved assets through a generated availability index and render deliberate placeholders for the rest. Approval state should control delivery, so incomplete art production never creates broken images or ships a rejected attempt. *(seen repeatedly)*
