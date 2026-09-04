/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Absolute origin of the API. Empty (the default) means same-origin, which is
   * what both production behind Caddy and the dev Vite proxy use. It exists for
   * a developer running the panel outside Docker against a remote server.
   */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
