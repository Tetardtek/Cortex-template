/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_BRAIN_API: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
