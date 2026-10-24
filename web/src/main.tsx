import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { PrefsProvider } from './lib/prefs';
import { registerServiceWorker } from './lib/pwa';
import './styles/tokens.css';
import './styles/motion.css';
import './styles/base.css';
import './styles/components.css';

registerServiceWorker();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <PrefsProvider>
      <App />
    </PrefsProvider>
  </StrictMode>,
);
