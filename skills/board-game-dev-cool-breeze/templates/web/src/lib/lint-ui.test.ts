// Enforce custom tooltips in Svelte and HTML without banning SVG <title> text.
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, it, expect } from 'vitest';
export function nativeTitles(source: string): string[] {
  return [...source.matchAll(/(?<![\w:-])title\s*=/g)].map((match) => match[0]);
}
function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(dir, entry.name);
    return entry.isDirectory() ? files(file) : /\.(svelte|html)$/.test(file) ? [file] : [];
  });
}
describe('own tooltips', () => {
  it('recognizes native title attributes', () => {
    expect(nativeTitles('<button title="tip">')).toHaveLength(1);
    expect(nativeTitles('<svg><title>Accessible name</title></svg>')).toHaveLength(0);
  });
  it('contains no native title attributes in source markup', () => {
    const root = path.resolve(import.meta.dirname, '..');
    expect(files(root).filter((file) => nativeTitles(readFileSync(file, 'utf8')).length)).toEqual([]);
  });
});
