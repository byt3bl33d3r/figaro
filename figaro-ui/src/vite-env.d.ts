/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_FIGARO_WS_URL: string;
  readonly VITE_FIGARO_API_URL: string;
  readonly VITE_VNC_DEFAULT_PASSWORD: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
