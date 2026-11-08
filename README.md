# board-game-dev-skill

An agent skill for building an online multiplayer board game from scratch with a team of coding
agents: rules capture, a server-authoritative rules engine, a phone-first web client, rooms with
token identity, moderators and spectators, bots, an art pipeline with inheritable themes, review
loops and self-hosting. It distils what worked, and what cost the most time, while agents built a
complete two-game platform.

This version of the skill is `board-game-dev-cool-breeze`.

## Install

```sh
npx skills add NightMachinery/board-game-dev-skill --global \
  --agent claude-code --skill board-game-dev-cool-breeze
```

The method assumes an agent that can run subagents, a machine with Go, Node with pnpm, tmux and
Caddy, and, for the art pipeline, a headless Chromium and an image-generation CLI.

## Use

Ask your agent, for example:

> Use board-game-dev-cool-breeze to start a new online game in the worker-placement genre for two
> to four players. Plan it end to end and run the build with workers.

The agent starts with a kickoff conversation: the game's original identity, its scope, the default
requirements, three to five candidate art themes to choose from, and where it will be hosted. Then
it bootstraps the repository from the templates and works milestone by milestone.

## What is inside

- [SKILL.md](skills/board-game-dev-cool-breeze/SKILL.md): the phases, defaults and the rules that
  matter most.
- [references/](skills/board-game-dev-cool-breeze/references/): one page per topic (architecture,
  rules capture, platform, phone UI, testing, bots, art, themes, orchestration, deployment, legal,
  pitfalls, milestones, default requirements), each with numbered lessons.
- [templates/](skills/board-game-dev-cool-breeze/templates/): tools to copy into a new game: the
  heavy-job guard, headless browser tools, the art pipeline, `self_host.py`, `AGENTS.md` and
  `Makefile` skeletons, worker brief templates and client helpers.
- [themes/](skills/board-game-dev-cool-breeze/themes/): reusable art directions with their colour
  tokens, starting with the Persian Safavid illuminated garden (light) and its night variant.

The skill builds original games. It implements mechanics in original code with original art and
wording, and does not recreate a published game's name, art or look.

## License

MIT. See [LICENSE](LICENSE).
