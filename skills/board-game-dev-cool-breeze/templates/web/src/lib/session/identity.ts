// Who this browser is (docs/protocol.md, hello):
//
//   - the identity token: 16 random bytes as 22 characters of unpadded
//     base64url, made once and kept in localStorage under my-game:token. The
//     server derives the user id from it; the same token is the same user.
//     It is a secret: never log it, show it or put it in a URL.
//   - the client id: random per page load, never stored. It pairs with the
//     tab's seq counter for idempotency; both start fresh together, which
//     the protocol requires (a client id must never be reused with a
//     counter that started over). Not keeping it in sessionStorage also
//     keeps a duplicated tab from sharing it.
//   - the display name, in localStorage under my-game:name.
//
// Storage can be missing or blocked (private mode, sandboxed frames); then
// the token lives only as long as the page.

// Set this once to project.json's name before adopting the template.
export const STORAGE_PREFIX = 'my-game:';
export const TOKEN_KEY = `${STORAGE_PREFIX}token`;
export const NAME_KEY = `${STORAGE_PREFIX}name`;

/** The longest display name the server accepts, in characters. */
export const MAX_NAME_LENGTH = 64;

/** The part of Storage identity uses. */
export type StorageLike = Pick<Storage, 'getItem' | 'setItem'>;

type RandomBytes = (bytes: Uint8Array<ArrayBuffer>) => Uint8Array<ArrayBuffer>;

const defaultRandom: RandomBytes = (bytes) => crypto.getRandomValues(bytes);

function defaultStorage(): StorageLike | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null; // reading localStorage itself can throw when it is blocked
  }
}

function read(storage: StorageLike | null, key: string): string | null {
  try {
    return storage?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function write(storage: StorageLike | null, key: string, value: string): void {
  try {
    storage?.setItem(key, value);
  } catch {
    // Blocked or full: the value still holds for this page.
  }
}

const BASE64URL = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

/** Unpadded base64url (RFC 4648 section 5). */
export function base64url(bytes: Uint8Array): string {
  let out = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const a = bytes[i]!;
    const b = bytes[i + 1];
    const c = bytes[i + 2];
    out += BASE64URL[a >> 2]!;
    out += BASE64URL[((a & 3) << 4) | ((b ?? 0) >> 4)]!;
    if (b !== undefined) out += BASE64URL[((b & 15) << 2) | ((c ?? 0) >> 6)]!;
    if (c !== undefined) out += BASE64URL[c & 63]!;
  }
  return out;
}

/**
 * Whether a string has the shape of a token: 22 base64url characters that
 * decode to exactly 16 bytes (the last character carries 2 data bits, so its
 * 4 low bits are zero).
 */
export function isValidToken(token: unknown): token is string {
  return typeof token === 'string' && /^[A-Za-z0-9_-]{21}[AQgw]$/.test(token);
}

/** A fresh random token. */
export function newToken(random: RandomBytes = defaultRandom): string {
  return base64url(random(new Uint8Array(16)));
}

/**
 * The stored token, or a fresh one stored in its place when there is none
 * or the stored value is not a valid token.
 */
export function loadToken(
  storage: StorageLike | null = defaultStorage(),
  random: RandomBytes = defaultRandom
): string {
  const stored = read(storage, TOKEN_KEY);
  if (isValidToken(stored)) return stored;
  const token = newToken(random);
  write(storage, TOKEN_KEY, token);
  return token;
}

/** A random client id for this page load. */
export function newClientId(random: RandomBytes = defaultRandom): string {
  if (random === defaultRandom && typeof crypto.randomUUID === 'function')
    return crypto.randomUUID();
  return base64url(random(new Uint8Array(16)));
}

// Control characters and invisible formatting characters (Unicode Cf),
// which the server refuses in any string, except the zero-width non-joiner
// and joiner (Persian, emoji sequences) and the emoji tag characters.
const FORBIDDEN = /[\p{Cc}\p{Cf}]/gu;

function allowedFormat(ch: string): boolean {
  const cp = ch.codePointAt(0) ?? 0;
  return cp === 0x200c || cp === 0x200d || (cp >= 0xe0020 && cp <= 0xe007f);
}

/**
 * A display name the server accepts: forbidden characters removed, outer
 * spaces trimmed, at most 64 characters (whole code points).
 */
export function cleanName(name: string): string {
  const kept = name.replace(FORBIDDEN, (ch) => (allowedFormat(ch) ? ch : '')).trim();
  return Array.from(kept).slice(0, MAX_NAME_LENGTH).join('').trim();
}

/** The stored display name, cleaned; empty when there is none. */
export function loadName(storage: StorageLike | null = defaultStorage()): string {
  return cleanName(read(storage, NAME_KEY) ?? '');
}

/** Stores a display name, cleaned, and returns what was stored. */
export function saveName(name: string, storage: StorageLike | null = defaultStorage()): string {
  const clean = cleanName(name);
  write(storage, NAME_KEY, clean);
  return clean;
}

/** This page's identity: the stored token and name, and a fresh client id. */
export interface Identity {
  token: string;
  clientId: string;
  name: string;
}

export function loadIdentity(storage: StorageLike | null = defaultStorage()): Identity {
  return { token: loadToken(storage), clientId: newClientId(), name: loadName(storage) };
}
