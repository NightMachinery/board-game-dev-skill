// Stable ids shared by tooltips, the overlay and /rules. Extend, do not rename.
export const RULE_SECTION_IDS = ['goal', 'setup', 'turn', 'scoring', 'glossary'] as const;
export type RuleSectionId = (typeof RULE_SECTION_IDS)[number];
export function isRuleSectionId(value: unknown): value is RuleSectionId {
  return typeof value === 'string' && (RULE_SECTION_IDS as readonly string[]).includes(value);
}
export const RULE_SECTIONS = RULE_SECTION_IDS.map((id) => ({
  id, titleKey: `rules.${id}.title`, bodyKey: `rules.${id}.body`
}));
