import { expect, it } from 'vitest';
import { socketUrl } from './socket-url';
it('preserves the page host and custom port while choosing the wire scheme', () => {
  expect(socketUrl({ protocol: 'http:', host: 'example.test:42111' })).toBe('ws://example.test:42111/ws');
  expect(socketUrl({ protocol: 'https:', host: 'example.test' })).toBe('wss://example.test/ws');
  expect(socketUrl({ protocol: 'http:', host: '[::1]:42111' })).toBe('ws://[::1]:42111/ws');
});
