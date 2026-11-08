import { expect, it } from 'vitest';
import { isRuleSectionId, RULE_SECTION_IDS, RULE_SECTIONS } from './sections';
it('has unique stable ids and translation keys for shared content', () => {
  expect(new Set(RULE_SECTION_IDS).size).toBe(RULE_SECTION_IDS.length);
  for (const section of RULE_SECTIONS) {
    expect(isRuleSectionId(section.id)).toBe(true);
    expect(section.titleKey).toBe(`rules.${section.id}.title`);
    expect(section.bodyKey).toBe(`rules.${section.id}.body`);
  }
  expect(isRuleSectionId('missing')).toBe(false); expect(isRuleSectionId(undefined)).toBe(false);
});
