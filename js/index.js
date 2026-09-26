// iLang loader. Don't learn iLang. Your AI should.
// Fetches the official iLang runtime, verifies its sha256, caches it for an hour, and
// falls back to the last verified copy when the network is unavailable. Node 18+.
import { createHash, randomBytes } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export const RUNTIME = "https://runtime.ilang.app";
export const FALLBACK = "https://raw.githubusercontent.com/ilang-ai/ilang-spec/main/runtime";   // the canon itself
const CANON = "https://raw.githubusercontent.com/ilang-ai/ilang-spec";                         // the canon at one commit
const OFFICIAL = ["https://runtime.ilang.app/", "https://raw.githubusercontent.com/ilang-ai/", "https://github.com/ilang-ai/", "https://ilang.ai/"];
const CHANNELS = ["latest"];
const COMMIT = /^[0-9a-f]{7,40}$/;
const VERSION = /^[0-9A-Za-z][0-9A-Za-z.-]*$/;
const MARKER = "<ilang-runtime";
const PREAMBLE =
  "You have loaded the official iLang runtime specification.\n\n" +
  "Treat the following content as the current official iLang protocol context.\n" +
  "Use it to interpret, structure, judge, execute, verify, and communicate where applicable.";

export class LoaderError extends Error {}

const sha = (buf) => createHash("sha256").update(buf).digest("hex");
const iso = (seconds) => (seconds ? new Date(seconds * 1000).toISOString().replace(/\.\d{3}Z$/, "Z") : null);

export class Loader {
  constructor({ runtime = RUNTIME, fallback, cacheDir, ttl = 3600, allowCustomSource = false, timeoutMs = 10000 } = {}) {
    if (fallback === undefined && runtime.replace(/\/+$/, "") === RUNTIME) fallback = FALLBACK;   // the canon repository, when the runtime host is down
    for (const url of [runtime, fallback || runtime]) {
      const u = url.replace(/\/+$/, "") + "/";
      if (!OFFICIAL.some((p) => u.startsWith(p)) && !allowCustomSource) {
        throw new Error("iLang loads only from official sources unless allowCustomSource is true");
      }
    }
    this.runtime = runtime.replace(/\/+$/, "");
    const fb = fallback ? fallback.replace(/\/+$/, "") : null;
    this.fallback = fb && fb !== this.runtime ? fb : null;
    this.origins = [this.runtime, this.fallback].filter(Boolean).map((u) => new URL(u).origin + "/");
    this.custom = allowCustomSource;
    this.cache = cacheDir || process.env.ILANG_CACHE_DIR ||
      join(process.env.XDG_CACHE_HOME || join(homedir(), ".cache"), "ilang");
    this.ttl = ttl;
    this.timeoutMs = timeoutMs;
    this.state = { loaded: false, channel: "latest", source: "none", version: null, sourceCommit: null,
      lastCheck: null, error: null };
    this.memo = new Map();
  }

  async #read(...parts) {
    try { return await readFile(join(this.cache, ...parts)); } catch { return null; }
  }

  async #write(data, ...parts) {
    const path = join(this.cache, ...parts);
    await mkdir(dirname(path), { recursive: true });
    const tmp = `${path}.${randomBytes(6).toString("hex")}.tmp`;
    await writeFile(tmp, data);
    await rename(tmp, path);                       // atomic: a reader never sees half a file
  }

  async #fetch(url) {
    if (!OFFICIAL.some((p) => url.startsWith(p)) && !(this.custom && this.origins.some((o) => url.startsWith(o)))) {
      throw new LoaderError(`refusing to fetch from ${url}`);
    }
    const res = await fetch(url, { headers: { "User-Agent": "ilang-loader-js/1.1.1" },
      signal: AbortSignal.timeout(this.timeoutMs) });
    if (!res.ok) throw new LoaderError(`${url}: HTTP ${res.status}`);
    return Buffer.from(await res.arrayBuffer());
  }

  // The runtime directory as it is at one commit. The runtime host serves only the current canon,
  // so a commit is read from the canon repository; any other source is laid out like
  // .../<ref>/runtime and has its ref replaced.
  #commitBase(commit) {
    if (this.runtime === RUNTIME) return `${CANON}/${commit}/runtime`;
    const refDir = this.runtime.endsWith("/runtime") ? this.runtime.slice(0, -"/runtime".length) : this.runtime;
    return `${refDir.slice(0, refDir.lastIndexOf("/"))}/${commit}/runtime`;
  }

  async #lastCheck() {
    const raw = await this.#read("state.json");
    if (!raw) return 0;
    const s = JSON.parse(raw);                     // the Python loader writes last_check
    return s.lastCheck || s.last_check || 0;
  }

  static #where(version, commit) {
    return commit ? ["commits", commit] : version ? ["versions", version] : ["latest"];
  }

  async #get(manifest, name, where, remote, base) {
    const meta = manifest.bundles[name];
    if (!meta) throw new LoaderError(`the runtime has no bundle named ${name}`);
    const cached = await this.#read(...where, `${name}.md`);
    if (cached && sha(cached) === meta.sha256) return [cached, false];
    if (!remote) throw new LoaderError(`no verified ${name} bundle in the cache`);
    const url = base ? `${base}/${meta.url.slice(meta.url.lastIndexOf("/") + 1)}` : meta.url;
    const data = await this.#fetch(url);
    if (data.length !== meta.bytes || sha(data) !== meta.sha256) {
      throw new LoaderError(`the ${name} bundle failed its sha256 check`);
    }
    return [data, true];
  }

  // Load from one source: the runtime host by default, or the fallback.
  async #load(names, version, commit, runtime = null) {
    const where = Loader.#where(version, commit);
    const pinned = Boolean(version || commit);
    const cached = await this.#read(...where, "manifest.json");
    let manifest = cached ? JSON.parse(cached) : null;
    let checked = false;
    const sourceDir = runtime || this.runtime;
    const base = commit ? this.#commitBase(commit) : version ? `${sourceDir}/versions/${version}` : sourceDir;
    if (!manifest || (!pinned && Date.now() / 1000 - (await this.#lastCheck()) >= this.ttl)) {
      manifest = JSON.parse(await this.#fetch(`${base}/manifest.json`));
      checked = true;
    }
    const got = [];
    for (const n of names) got.push(await this.#get(manifest, n, where, true, base));
    for (let i = 0; i < names.length; i++) {         // write only once everything has verified
      if (got[i][1]) await this.#write(got[i][0], ...where, `${names[i]}.md`);
    }
    if (checked) {
      await this.#write(JSON.stringify(manifest), ...where, "manifest.json");
      if (!pinned) {
        const now = Date.now() / 1000;
        await this.#write(JSON.stringify({ lastCheck: now, last_check_at: iso(now), last_success_at: iso(now),
          active_version: manifest.version, source: "remote", status: "ok" }), "state.json");
      }
    }
    const source = checked || got.some(([, fresh]) => fresh) ? "remote" : "cache";
    return [manifest, got.map(([data]) => data.toString("utf8")), source];
  }

  /** The runtime text, or null when nothing verified is available and strict is off.
   * version or commit pins an exact runtime; both are immutable, so a pinned runtime is fetched
   * once and then served from disk. */
  async load({ extensions = [], version = null, commit = null, channel = "latest", strict = false } = {}) {
    if (!CHANNELS.includes(channel)) {
      throw new Error(`channel ${JSON.stringify(channel)} is not available; use "latest", or pin with version or commit`);
    }
    if (version && commit) throw new Error("pin with version or commit, not both");
    if (commit !== null && !COMMIT.test(commit)) throw new Error("commit must be 7 to 40 lowercase hex characters");
    if (version !== null && !VERSION.test(version)) throw new Error("version must look like 2026.09.22-a69b7d69b3a6");
    const names = ["core", ...extensions.filter((e) => e !== "core")];
    const key = JSON.stringify([names, version, commit]);
    const hit = this.memo.get(key);
    if (hit && (version || commit || Date.now() / 1000 - hit.at < this.ttl)) {
      Object.assign(this.state, hit.state);
      return hit.text;
    }
    let manifest, texts, source;
    try {
      [manifest, texts, source] = await this.#load(names, version, commit);
      this.state.error = null;
    } catch (err) {
      this.state.error = `${err.name}: ${err.message}`;
      if (this.fallback && !commit) {                // a commit is already read from the canon
        try {
          [manifest, texts, source] = await this.#load(names, version, commit, this.fallback);
          this.state.error = null;
        } catch (err2) {
          this.state.error += `; fallback ${err2.name}: ${err2.message}`;
        }
      }
    }
    if (this.state.error !== null) {
      try {                                          // Last Known Good, never the network
        const where = Loader.#where(version, commit);
        manifest = JSON.parse((await this.#read(...where, "manifest.json")) || "null");
        texts = [];
        for (const n of names) texts.push((await this.#get(manifest, n, where, false))[0].toString("utf8"));
        source = "cache";
      } catch {
        if (strict) throw new LoaderError(this.state.error);
        Object.assign(this.state, { loaded: false, source: "none" });
        return null;
      }
    }
    Object.assign(this.state, { loaded: true, source, version: manifest.version,
      channel: version || commit ? "pinned" : "latest",
      sourceCommit: manifest.source_commit, lastCheck: (await this.#lastCheck()) || null });
    const text = texts.join("\n\n");
    if (this.state.error === null) {
      const { loaded, channel: ch, version: v, sourceCommit } = this.state;
      this.memo.set(key, { text, at: Date.now() / 1000, state: { loaded, channel: ch, source, version: v, sourceCommit } });
    }
    return text;
  }
}

const hasRuntime = (m) => {
  const c = m && m.content;
  if (typeof c === "string") return c.includes(MARKER);
  if (Array.isArray(c)) return c.some((p) => p && String(p.text ?? "").includes(MARKER));
  return false;
};

let loader = null;

/** Replace the default loader, e.g. configure({ cacheDir, ttl }). */
export function configure(options = {}) {
  loader = new Loader(options);
  return loader;
}

const current = () => loader || configure();

/** Load the runtime now. Returns its text, or null if nothing verified is available. */
export const load = (options) => current().load(options);

/** The runtime as a system-prompt string, or "" when it could not be loaded. */
export async function system(options) {
  const text = await load(options);
  if (text === null) return "";
  return `${PREAMBLE}\n\n<ilang-runtime version="${current().state.version}">\n${text}\n</ilang-runtime>`;
}

/** Messages with the iLang runtime in front. The runtime is the first system message; with
 * mergeSystem it is put at the start of the application's system message, for providers that
 * accept only one. The user's messages are never modified, and the runtime is added only once,
 * so wrapping every turn is safe. */
export async function wrap(messages, options = {}) {
  const { mergeSystem = false, ...loadOptions } = options;
  const list = [...messages];
  if (list.some(hasRuntime)) return list;
  const block = await system(loadOptions);
  if (!block) return list;
  if (mergeSystem) {
    const i = list.findIndex((m) => m && m.role === "system");
    if (i >= 0) {
      const c = list[i].content;
      const merged = Array.isArray(c) ? [{ type: "text", text: block }, ...c] : c ? `${block}\n\n${c}` : block;
      list[i] = { ...list[i], content: merged };
      return list;
    }
  }
  return [{ role: "system", content: block }, ...list];
}

/** What is loaded: version, commit, where it came from, cache age and any last error. */
export function status() {
  const st = current().state;
  const s = { brand: "iLang", ...st, commit: st.sourceCommit, lastCheck: iso(st.lastCheck) };
  if (st.lastCheck) s.ageSeconds = Math.floor(Date.now() / 1000 - st.lastCheck);
  return s;
}

export default { load, wrap, system, status, configure, Loader, LoaderError, RUNTIME, FALLBACK };
