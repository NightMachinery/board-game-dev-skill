# Bitmap art direction skeleton

Copy this structure to `themes/<id>/style.md`. Define one coherent look per
theme. A dark look is another theme with its own `mode`, never an OS switch.
Keep subjects in game-wide `art/subjects.json`; optional theme subjects override
individual entries. Original illustrations only, no copied official game art.

## Style prefix (verbatim)

Technique only: medium, line, palette rules and the bans. Every word here goes
into every prompt, so a motif, sky or ground named here repeats across the
whole set.

> Original illustration with a clear silhouette, a restrained palette and
> readable shapes at card size. No lettering, pseudo-writing, numbers, logos,
> painted frames or watermarks.

## Palette

Choose named palette roles and exact colour values matching interface tokens.
Describe foreground/background separation and treatment of shadows.

## Motif pool

Name the materials, marks and scenery that subjects may draw from. Each
subject names only what it needs; across one kind, no motif should appear in
more than about a third of the pictures. Framing and safe crops belong in the
kind templates.

## Variety per kind

For each kind with many members, list named composition schemes and viewpoints
and require a spread across them, then the free variables (season, hour,
weather, terrain). Tie each fact players need from the picture to one
whole-scene variable. Related members differ by composition, approach or hour,
not by a small rearrangement.

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
Then review each batch as a set on one thumbnail contact sheet, as described in
the skill's art reference under "Variety and one visual world".
