import { describe, expect, it } from 'vitest';
import {
  base64url,
  cleanName,
  isValidToken,
  loadIdentity,
  loadName,
  loadToken,
  MAX_NAME_LENGTH,
  NAME_KEY,
  newClientId,
  newToken,
  saveName,
  TOKEN_KEY,
  type StorageLike
} from './identity';

function memory(initial: Record<string, string> = {}): StorageLike & { data: Map<string, string> } {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => void data.set(k, v)
  };
}

const blocked: StorageLike = {
  getItem: () => {
    throw new Error('SecurityError');
  },
  setItem: () => {
    throw new Error('SecurityError');
  }
};

describe('base64url', () => {
  it('matches RFC 4648 test vectors, unpadded and url-safe', () => {
    const enc = (s: string) => base64url(new TextEncoder().encode(s));
    expect(enc('')).toBe('');
    expect(enc('f')).toBe('Zg');
    expect(enc('fo')).toBe('Zm8');
    expect(enc('foo')).toBe('Zm9v');
    expect(enc('foob')).toBe('Zm9vYg');
    expect(enc('fooba')).toBe('Zm9vYmE');
    expect(enc('foobar')).toBe('Zm9vYmFy');
    expect(base64url(new Uint8Array([0xfb, 0xff]))).toBe('-_8');
  });
});

describe('the identity token', () => {
  it('is 16 random bytes as 22 base64url characters', () => {
    const token = newToken();
    expect(token).toMatch(/^[A-Za-z0-9_-]{22}$/);
    expect(isValidToken(token)).toBe(true);
    expect(newToken()).not.toBe(token);
    const fixed = newToken((b) => b.fill(255));
    expect(fixed).toBe('_____________________w');
    expect(isValidToken(fixed)).toBe(true);
  });

  it('rejects anything a server would refuse', () => {
    for (const bad of [
      '',
      'tok-a',
      'AAAAAAAAAAAAAAAAAAAAA', // 21
      'AAAAAAAAAAAAAAAAAAAAAAA', // 23
      'AAAAAAAAAAAAAAAAAAAAA=',
      'AAAAAAAAAAAAAAAAAAAA+A',
      'AAAAAAAAAAAAAAAAAAAAAB', // 4 low bits set in the last character
      null,
      42
    ]) {
      expect(isValidToken(bad), String(bad)).toBe(false);
    }
  });

  it('is created once and then read back', () => {
    const storage = memory();
    const token = loadToken(storage);
    expect(storage.data.get(TOKEN_KEY)).toBe(token);
    expect(loadToken(storage)).toBe(token);
  });

  it('replaces a stored value that is not a valid token', () => {
    const storage = memory({ [TOKEN_KEY]: 'tok-a' });
    const token = loadToken(storage);
    expect(isValidToken(token)).toBe(true);
    expect(storage.data.get(TOKEN_KEY)).toBe(token);
  });

  it('still works when storage is blocked or missing', () => {
    expect(isValidToken(loadToken(blocked))).toBe(true);
    expect(isValidToken(loadToken(null))).toBe(true);
  });
});

describe('the client id', () => {
  it('is random for every page load', () => {
    const a = newClientId();
    expect(a.length).toBeGreaterThanOrEqual(22);
    expect(a.length).toBeLessThanOrEqual(128);
    expect(newClientId()).not.toBe(a);
    expect(newClientId((b) => b.fill(0))).toBe('AAAAAAAAAAAAAAAAAAAAAA');
  });

  it('is never stored', () => {
    const storage = memory();
    const id = loadIdentity(storage);
    expect([...storage.data.values()]).not.toContain(id.clientId);
    expect(loadIdentity(storage).clientId).not.toBe(id.clientId);
    expect(loadIdentity(storage).token).toBe(id.token);
  });
});

describe('the display name', () => {
  it('is stored cleaned and read back', () => {
    const storage = memory();
    expect(saveName('  Roshan  ', storage)).toBe('Roshan');
    expect(storage.data.get(NAME_KEY)).toBe('Roshan');
    expect(loadName(storage)).toBe('Roshan');
    expect(loadName(memory())).toBe('');
    expect(loadName(blocked)).toBe('');
  });

  it('drops control and invisible formatting characters but keeps joiners', () => {
    expect(cleanName('Sa\u0000ra\u202E')).toBe('Sara');
    expect(cleanName('a\u200Bb\uFEFFc\u2066d')).toBe('abcd');
    expect(cleanName('می\u200Cخواهم')).toBe('می\u200Cخواهم');
    expect(cleanName('👩\u200D💻')).toBe('👩\u200D💻');
  });

  it('keeps at most 64 characters, counting code points', () => {
    expect(cleanName('x'.repeat(100))).toHaveLength(MAX_NAME_LENGTH);
    const emoji = cleanName('😀'.repeat(70));
    expect(Array.from(emoji)).toHaveLength(MAX_NAME_LENGTH);
  });
});
