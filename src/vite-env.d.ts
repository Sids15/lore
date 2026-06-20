/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the Python sidecar (FastAPI). Set in `.env`. */
  readonly VITE_SIDECAR_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
