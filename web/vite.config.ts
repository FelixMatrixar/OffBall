import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

/** Files in public/ that belong to the app shell. */
const PUBLIC_SHELL = ['./', 'index.html', 'favicon.svg', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/icon-512.png', 'icons/maskable-512.png', 'icons/apple-touch-icon.png'];

/**
 * Emits sw.js (src/pwa/sw.js) with the app shell's hashed file names: the entry script, what it imports, the
 * stylesheet and the field worker. Lazy chunks (charts, 3D) aren't in the shell; they're cached when first used.
 */
function serviceWorker(): Plugin {
  return {
    name: 'offball-service-worker',
    apply: 'build',
    generateBundle(_options, bundle) {
      const files = Object.values(bundle);
      const shell = new Set<string>();
      const add = (name: string) => {
        if (shell.has(name)) return;
        shell.add(name);
        const chunk = bundle[name];
        if (chunk?.type === 'chunk') for (const dep of chunk.imports) add(dep);
      };
      for (const f of files) {
        if (f.type === 'chunk' && f.isEntry) add(f.fileName);
        if (f.type === 'asset' && (f.fileName.endsWith('.css') || /worker/.test(f.fileName))) add(f.fileName);
      }
      const list = [...PUBLIC_SHELL, ...[...shell].sort()];
      const version = createHash('sha256').update(list.join('\n')).digest('hex').slice(0, 12);
      const source = `const VERSION = ${JSON.stringify(version)};\nconst SHELL = ${JSON.stringify(list)};\n${readFileSync(new URL('./src/pwa/sw.js', import.meta.url), 'utf8')}`;
      this.emitFile({ type: 'asset', fileName: 'sw.js', source });
    },
  };
}

export default defineConfig({
  plugins: [react(), serviceWorker()],
  server: { port: 5173, strictPort: true },
});
