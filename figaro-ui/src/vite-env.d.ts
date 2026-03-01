/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_FIGARO_WS_URL: string;
  readonly VITE_FIGARO_API_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
