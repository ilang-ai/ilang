export declare const RUNTIME: string;

export declare class LoaderError extends Error {}

export interface LoadOptions {
  /** Extra bundles besides the core, e.g. ["media"] for image, video and audio work. */
  extensions?: string[];
  /** Pin an exact runtime version for reproducible runs, e.g. "2026.09.22-a69b7d69b3a6". */
  version?: string | null;
  /** Throw instead of failing open when no verified runtime is available. */
  strict?: boolean;
}

export interface LoaderOptions {
  runtime?: string;
  cacheDir?: string;
  /** Seconds between checks for a new version. Default 3600. */
  ttl?: number;
  allowCustomSource?: boolean;
  timeoutMs?: number;
}

export interface Status {
  brand: "iLang";
  loaded: boolean;
  source: "remote" | "cache" | "none";
  version: string | null;
  sourceCommit: string | null;
  lastCheck: number | null;
  ageSeconds?: number;
  error: string | null;
}

export type Message = { role: string; content: unknown; [key: string]: unknown };

export declare class Loader {
  constructor(options?: LoaderOptions);
  state: Omit<Status, "brand" | "ageSeconds">;
  load(options?: LoadOptions): Promise<string | null>;
}

export declare function configure(options?: LoaderOptions): Loader;
export declare function load(options?: LoadOptions): Promise<string | null>;
export declare function system(options?: LoadOptions): Promise<string>;
export declare function wrap<M extends Message>(messages: M[], options?: LoadOptions): Promise<(M | Message)[]>;
export declare function status(): Status;

declare const _default: {
  load: typeof load; wrap: typeof wrap; system: typeof system; status: typeof status;
  configure: typeof configure; Loader: typeof Loader; LoaderError: typeof LoaderError; RUNTIME: string;
};
export default _default;
