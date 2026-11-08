# Bitmap art direction skeleton

Copy this structure to `themes/<id>/style.md`. Define one coherent look per
theme. A dark look is another theme with its own `mode`, never an OS switch.
Keep subjects in game-wide `art/subjects.json`; optional theme subjects override
individual entries. Original illustrations only, no copied official game art.

## Style prefix (verbatim)

> Original illustration with a clear silhouette, a restrained palette and
> readable shapes at card size. No lettering, numbers, logos or watermarks.

## Palette

Choose named palette roles and exact colour values matching interface tokens.
Describe foreground/background separation and treatment of shadows.

## Motifs

Name recurring materials, marks, framing and composition. Specify safe crops.

## Do and don't

- Keep game information in translatable UI and vectors, outside the painting.
- Check the actual shipped size, crop and low-resolution thumbnail.
- Avoid text, borders that conflict with UI, copied emblems and tiny detail.
- Use a style reference only when requested; same-subject anchors can produce
  near-copies rather than a distinct illustration.

## Kind templates

**card**: "A clear view of {subject}, with {accent} accents and generous crop room."

**token**: "One bold image of {subject}, with {accent} accents, centred in a square."

## Review

Inspect every attempt and the shipped crop. Record id, exact attempt,
fingerprint, reviewer, reasons and approved/rejected status. No script can
approve artistic quality. Preserve rejected costly generations outside git.
