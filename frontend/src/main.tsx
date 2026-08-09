import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';

import App from './App';
import './styles/global.css';


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
