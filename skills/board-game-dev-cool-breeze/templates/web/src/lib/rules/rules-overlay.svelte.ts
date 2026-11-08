// Mount RulesOverlay once in the root layout; keep a single controller.
import { isRuleSectionId, type RuleSectionId } from './sections';
export class RulesOverlayState {
  open = $state(false);
  section = $state<RuleSectionId | undefined>();
  request = $state(0);
  openedOn = $state('');
  show(section: unknown, pathname: string): void {
    this.section = isRuleSectionId(section) ? section : undefined;
    this.openedOn = pathname; this.request += 1; this.open = true;
  }
  hide(): void { this.open = false; }
}
export const rulesOverlay = new RulesOverlayState();
export function openRules(sectionId?: RuleSectionId | string): void {
  rulesOverlay.show(sectionId, globalThis.location?.pathname ?? '');
}
export function closeRules(): void { rulesOverlay.hide(); }
