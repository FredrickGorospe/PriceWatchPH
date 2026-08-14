import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';

// Loaded before the app so component modules always win the cascade over the
// shared `pw-` material classes.
import './styles/global.css';
import App from './App';


const rootElement = document.getElementById('root');

if (!rootElement) {
  throw new Error('PriceWatch PH could not find its application root.');
}

createRoot(rootElement).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
