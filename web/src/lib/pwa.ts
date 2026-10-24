// The installable app (PRD 4.3): registers the service worker in production builds and offers a new version when one
// has installed, rather than swapping it in under the viewer.
type Listener = () => void;

let waiting: ServiceWorker | null = null;
const listeners = new Set<Listener>();

export const pwaUpdate = {
  subscribe: (fn: Listener) => {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
  /** The new version, installed and waiting, or null. */
  get: () => waiting,
  /** Switches to the new version; the page reloads once it takes over. */
  apply: () => waiting?.postMessage({ type: 'SKIP_WAITING' }),
};

export function registerServiceWorker(): void {
  if (!import.meta.env.PROD || !('serviceWorker' in navigator)) return;
  // A page that had no worker yet is being claimed for the first time, not updated: no reload for that.
  const hadController = !!navigator.serviceWorker.controller;
  let reloading = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!hadController || reloading) return;
    reloading = true;
    window.location.reload();
  });
  const offer = (worker: ServiceWorker) => {
    waiting = worker;
    listeners.forEach((l) => l());
  };
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register(`${import.meta.env.BASE_URL}sw.js`)
      .then((reg) => {
        if (reg.waiting && navigator.serviceWorker.controller) offer(reg.waiting);
        reg.addEventListener('updatefound', () => {
          const worker = reg.installing;
          worker?.addEventListener('statechange', () => {
            if (worker.state === 'installed' && navigator.serviceWorker.controller) offer(worker);
          });
        });
      })
      .catch(() => undefined);
  });
}
