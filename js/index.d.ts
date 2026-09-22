export declare const RUNTIME: string;

export declare class LoaderError extends Error {}

export interface LoadOptions {
  /** Extra bundles besides the core, e.g. ["media"] for image, video and audio work. */
  extensions?: string[];
  /** Pin an exact runtime version for reproducible runs, e.g. "2026.09.22-a69b7d69b3a6". */
  version?: string | null;
  /** Pin the runtime as it is at one commit of the canon repository (7 to 40 hex characters). */
  commit?: string | null;
  /** "latest" is the only channel in this version; pin with version or commit instead. */
  channel?: "latest";
  /** Throw instead of failing open when no verified runtime is available. */
  strict?: boolean;
}

export interface WrapOptions extends LoadOptions {
  /** Put the runtime at the start of the application's system message instead of adding a
   * separate one, for providers that accept a single system message. */
  mergeSystem?: boolean;
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
  channel: "latest" | "pinned";
  source: "remote" | "cache" | "none";
  version: string | null;
  commit: string | null;
  sourceCommit: string | null;
  /** When the loader last checked for a new version, ISO 8601 UTC. */
  lastCheck: string | null;
  ageSeconds?: number;
  error: string | null;
}

export type Message = { role: string; content: unknown; [key: string]: unknown };

export declare class Loader {
  constructor(options?: LoaderOptions);
  state: { loaded: boolean; channel: "latest" | "pinned"; source: "remote" | "cache" | "none";
    version: string | null; sourceCommit: string | null; lastCheck: number | null; error: string | null };
  load(options?: LoadOptions): Promise<string | null>;
}

export declare function configure(options?: LoaderOptions): Loader;
export declare function load(options?: LoadOptions): Promise<string | null>;
export declare function system(options?: LoadOptions): Promise<string>;
export declare function wrap<M extends Message>(messages: M[], options?: WrapOptions): Promise<(M | Message)[]>;
export declare function status(): Status;

declare const _default: {
  load: typeof load; wrap: typeof wrap; system: typeof system; status: typeof status;
  configure: typeof configure; Loader: typeof Loader; LoaderError: typeof LoaderError; RUNTIME: string;
};
export default _default;
