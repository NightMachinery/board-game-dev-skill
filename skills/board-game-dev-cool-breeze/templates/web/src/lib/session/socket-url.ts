// Same origin works with Caddy, reverse proxies, HTTP intranets and TLS.
export function socketUrl(location: Pick<Location, 'protocol' | 'host'> = globalThis.location): string {
  if (!['http:', 'https:'].includes(location.protocol)) throw new Error('expected an HTTP(S) page');
  return `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`;
}
