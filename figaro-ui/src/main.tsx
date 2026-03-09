import { initTracing } from './tracing';
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

initTracing();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
