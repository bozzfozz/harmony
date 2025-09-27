declare interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_API_BASE_PATH?: string;
}

declare interface ImportMeta {
  readonly env: ImportMetaEnv;
}
