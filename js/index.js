// iLang loader. Don't learn iLang. Your AI should.
// Fetches the official iLang runtime, verifies its sha256, caches it for an hour, and
// falls back to the last verified copy when the network is unavailable. Node 18+.
import { createHash, randomBytes } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export const RUNTIME = "https://raw.githubusercontent.com/ilang-ai/ilang-spec/main/runtime";
const OFFICIAL = ["https://raw.githubusercontent.com/ilang-ai/", "https://github.com/ilang-ai/", "https://ilang.ai/"];
const MARKER = "<ilang-runtime";
const PREAMBLE =
  "You have loaded the official iLang runtime specification.\n\n" +
  "Treat the following content as the current official iLang protocol context.\n" +
  "Use it to interpret, structure, judge, execute, verify, and communicate where applicable.";

export class LoaderError extends Error {}

const sha = (buf) => createHash("sha256").update(buf).digest("hex");

export class Loader {
  constructor({ runtime = RUNTIME, cacheDir, ttl = 3600, allowCustomSource = false, timeoutMs = 10000 } = {}) {
    if (!OFFICIAL.some((p) => runtime.startsWith(p)) && !allowCustomSource) {
      throw new Error("iLang loads only from official sources unless allowCustomSource is true");
    }
    this.runtime = runtime.replace(/\/+$/, "");
    this.cache = cacheDir || process.env.ILANG_CACHE_DIR ||
      join(process.env.XDG_CACHE_HOME || join(homedir(), ".cache"), "ilang");
    this.ttl = ttl;
    this.timeoutMs = timeoutMs;
    this.state = { loaded: false, source: "none", version: null, sourceCommit: null, lastCheck: null, error: null };
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
    if (!OFFICIAL.some((p) => url.startsWith(p)) && !url.startsWith(this.runtime)) {
      throw new LoaderError(`refusing to fetch from ${url}`);
    }
    const res = await fetch(url, { headers: { "User-Agent": "ilang-loader-js/1.0.0" },
      signal: AbortSignal.timeout(this.timeoutMs) });
    if (!res.ok) throw new LoaderError(`${url}: HTTP ${res.status}`);
    return Buffer.from(await res.arrayBuffer());
  }

  async #lastCheck() {
    const raw = await this.#read("state.json");
    return raw ? JSON.parse(raw).lastCheck || 0 : 0;
  }

  async #get(manifest, name, where, remote) {
    const meta = manifest.bundles[name];
    if (!meta) throw new LoaderError(`the runtime has no bundle named ${name}`);
    const cached = await this.#read(...where, `${name}.md`);
    if (cached && sha(cached) === meta.sha256) return [cached, false];
    if (!remote) throw new LoaderError(`no verified ${name} bundle in the cache`);
    const data = await this.#fetch(meta.url);
    if (data.length !== meta.bytes || sha(data) !== meta.sha256) {
      throw new LoaderError(`the ${name} bundle failed its sha256 check`);
    }
    return [data, true];
  }

  async #load(names, version) {
    const where = version ? ["versions", version] : ["latest"];
    const cached = await this.#read(...where, "manifest.json");
    let manifest = cached ? JSON.parse(cached) : null;
    let checked = false;
    if (!manifest || (!version && Date.now() / 1000 - (await this.#lastCheck()) >= this.ttl)) {
      const url = version ? `${this.runtime}/versions/${version}/manifest.json` : `${this.runtime}/manifest.json`;
      manifest = JSON.parse(await this.#fetch(url));
      checked = true;
    }
    const got = [];
    for (const n of names) got.push(await this.#get(manifest, n, where, true));
    for (let i = 0; i < names.length; i++) {         // write only once everything has verified
      if (got[i][1]) await this.#write(got[i][0], ...where, `${names[i]}.md`);
    }
    if (checked) {
      await this.#write(JSON.stringify(manifest), ...where, "manifest.json");
      if (!version) await this.#write(JSON.stringify({ lastCheck: Date.now() / 1000 }), "state.json");
    }
    const source = checked || got.some(([, fresh]) => fresh) ? "remote" : "cache";
    return [manifest, got.map(([data]) => data.toString("utf8")), source];
  }

  /** The runtime text, or null when nothing verified is available and strict is off. */
  async load({ extensions = [], version = null, strict = false } = {}) {
    const names = ["core", ...extensions.filter((e) => e !== "core")];
    const key = JSON.stringify([names, version]);
    const hit = this.memo.get(key);
    if (hit && (version || Date.now() / 1000 - hit.at < this.ttl)) {
      Object.assign(this.state, hit.state);
      return hit.text;
    }
    let manifest, texts, source;
    try {
      [manifest, texts, source] = await this.#load(names, version);
      this.state.error = null;
    } catch (err) {
      this.state.error = `${err.name}: ${err.message}`;
      try {                                          // Last Known Good, never the network
        const where = version ? ["versions", version] : ["latest"];
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
      sourceCommit: manifest.source_commit, lastCheck: (await this.#lastCheck()) || null });
    const text = texts.join("\n\n");
    if (this.state.error === null) {
      const { loaded, version: v, sourceCommit } = this.state;
      this.memo.set(key, { text, at: Date.now() / 1000, state: { loaded, source, version: v, sourceCommit } });
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

/** Messages with the iLang runtime as the first system message. The user's messages are
 * never modified, and the runtime is added only once, so wrapping every turn is safe. */
export async function wrap(messages, options) {
  const list = [...messages];
  if (list.some(hasRuntime)) return list;
  const block = await system(options);
  return block ? [{ role: "system", content: block }, ...list] : list;
}

/** What is loaded: version, source commit, where it came from and any last error. */
export function status() {
  const s = { brand: "iLang", ...current().state };
  if (s.lastCheck) s.ageSeconds = Math.floor(Date.now() / 1000 - s.lastCheck);
  return s;
}

export default { load, wrap, system, status, configure, Loader, LoaderError, RUNTIME };
