export declare const RUNTIME: string;
/** Where the same files are read when the runtime host does not answer: the canon repository. */
export declare const FALLBACK: string;

export declare class LoaderError extends Error {}

export interface LoadOptions {
  /** Extra bundles besides the core, e.g. ["media"] for image, video and audio work. */
  extensions?: string[];
  /** Pin an exact runtime version for reproducible runs, e.g. "2026.11.19-105ffdc14ac2". Set strict
   * with a pin, so that a pin that cannot be loaded throws. */
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
  /** A second source for the same files, read when runtime does not answer. Default: FALLBACK
   * when runtime is the default, otherwise none. null for none. */
  fallback?: string | null;
  cacheDir?: string;
  /** Seconds between checks for a new version. Default 3600. */
  ttl?: number;
  allowCustomSource?: boolean;
  /** Milliseconds one request may take. Default 10000. */
  timeoutMs?: number;
}

export interface Status {
  brand: "iLang";
  loaded: boolean;
  channel: "latest" | "pinned";
  source: "remote" | "cache" | "none";
  version: string | null;
  /** The canon commit the loaded bundle was built from. Not a value for the commit option: the
   * bundle built from a commit is committed after it, so pinning that commit loads the build
   * before. To load the same runtime again, pin version with the version reported here. */
  commit: string | null;
  sourceCommit: string | null;
  /** When the loader last checked for a new version, ISO 8601 UTC. */
  lastCheck: string | null;
  ageSeconds?: number;
  error: string | null;
}

/** A plain message object. wrap() also takes the message types of an SDK as they are. */
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
/** The messages with the runtime in front. The caller's messages keep their type, so M can be an
 * SDK's own message type, with its literal roles, optional content and extra fields. */
export declare function wrap<M extends { role?: unknown; content?: unknown }>(
  messages: readonly M[], options?: WrapOptions): Promise<(M | { role: "system"; content: string })[]>;
export declare function status(): Status;

declare const _default: {
  load: typeof load; wrap: typeof wrap; system: typeof system; status: typeof status;
  configure: typeof configure; Loader: typeof Loader; LoaderError: typeof LoaderError; RUNTIME: string;
  FALLBACK: string;
};
export default _default;
