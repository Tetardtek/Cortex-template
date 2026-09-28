/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_USE_MOCK: string
  readonly VITE_BRAIN_API: string
  readonly VITE_BRAIN_TOKEN: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
