import { expect, it } from 'vitest';
import { applyTheme, type ThemeIndex } from './theme';
it('applies only the selected mode and removes stale tokens on selection', () => {
  const properties = new Map<string, string>();
  const target = { style: { setProperty: (k: string, v: string) => properties.set(k, v),
    removeProperty: (k: string) => properties.delete(k), colorScheme: '' }, dataset: { theme: '' } };
  const base = { id: 'base', name: 'Base', mode: 'light', tokens: { paper: '#fff', colours: { ink: '#111' } }, assets: {} } satisfies ThemeIndex;
  applyTheme(base, target as unknown as HTMLElement);
  expect(target.style.colorScheme).toBe('light'); expect(properties.get('--colours-ink')).toBe('#111');
  applyTheme({ ...base, id: 'night', mode: 'dark', tokens: { paper: '#111' } }, target as unknown as HTMLElement);
  expect(target.dataset.theme).toBe('night'); expect(target.style.colorScheme).toBe('dark');
  expect(properties.has('--colours-ink')).toBe(false);
});
