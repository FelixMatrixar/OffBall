// The offline buffer: the last 10 minutes of a live feed, kept on the device in IndexedDB (PRD 15.11).
import type { ClientMessage } from './types';

const DB = 'offball';
const STORE = 'feed-buffers';

function openAt(version?: number): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') return reject(new Error('IndexedDB unavailable'));
    const req = indexedDB.open(DB, version);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/** Opens the database, repairing one that exists without the buffer store (made by another page or an old version). */
async function open(): Promise<IDBDatabase> {
  const db = await openAt();
  if (db.objectStoreNames.contains(STORE)) return db;
  const next = db.version + 1;
  db.close();
  return openAt(next);
}

export async function saveBuffer(matchId: string, messages: readonly ClientMessage[]): Promise<void> {
  if (!messages.length) return;
  try {
    const db = await open();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).put({ savedAt: Date.now(), messages: [...messages] }, matchId);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    db.close();
  } catch {
    // Private mode or a full disk: the buffer is a convenience, never required.
  }
}

export async function loadBuffer(matchId: string): Promise<{ savedAt: number; messages: ClientMessage[] } | null> {
  try {
    const db = await open();
    const value = await new Promise<{ savedAt: number; messages: ClientMessage[] } | undefined>((resolve, reject) => {
      const req = db.transaction(STORE, 'readonly').objectStore(STORE).get(matchId);
      req.onsuccess = () => resolve(req.result as { savedAt: number; messages: ClientMessage[] } | undefined);
      req.onerror = () => reject(req.error);
    });
    db.close();
    return value ?? null;
  } catch {
    return null;
  }
}
