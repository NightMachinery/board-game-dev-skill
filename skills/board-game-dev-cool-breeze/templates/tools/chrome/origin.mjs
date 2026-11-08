// Frontend URL comes from the serving tool, never the backend's default port.
import { readFileSync } from 'node:fs';
export function frontendOrigin(env = process.env, file = new URL('../../.self-host/config.json', import.meta.url)) {
  let url = env.BGD_ORIGIN;
  if (!url) {
    try { url = JSON.parse(readFileSync(file, 'utf8')).url; }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  if (!url) throw new Error('pass --origin with the served frontend URL, set BGD_ORIGIN, or run self_host.py first');
  const parsed = new URL(url);
  if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('frontend origin must use http(s)');
  return parsed.origin;
}
