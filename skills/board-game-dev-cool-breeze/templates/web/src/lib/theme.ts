// Import/fetch exactly the chosen generated index. A dark pack is explicit.
export interface ThemeIndex {
  id: string;
  name: string;
  mode: 'light' | 'dark';
  tokens: { [key: string]: string | number | ThemeIndex['tokens'] };
  assets: Record<string, null | { sourceTheme: string; sizes: Record<string, { url: string; w: number; h: number }> }>;
}
let applied: string[] = [];
export function applyTheme(theme: ThemeIndex, target: HTMLElement = document.documentElement): void {
  if (!['light', 'dark'].includes(theme.mode)) throw new Error('theme needs a light or dark mode');
  for (const key of applied) target.style.removeProperty(key);
  applied = [];
  const put = (tokens: ThemeIndex['tokens'], prefix = '') => {
    for (const [key, value] of Object.entries(tokens)) {
      const name = `${prefix}${key}`;
      if (!/^[a-zA-Z][a-zA-Z0-9-]*$/.test(name)) throw new Error('invalid theme token');
      if (typeof value === 'object') put(value, `${name}-`);
      else { const variable = `--${name}`; target.style.setProperty(variable, String(value)); applied.push(variable); }
    }
  };
  put(theme.tokens);
  target.style.colorScheme = theme.mode;
  target.dataset.theme = theme.id;
}
