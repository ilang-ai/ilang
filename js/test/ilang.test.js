// Offline tests: a local HTTP server plays the official runtime.  node --test test/ilang.test.js
// ILANG_NETWORK_TESTS=1 also checks the real official runtime.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterEach, beforeEach, describe, test } from "node:test";
import * as ilang from "../index.js";
import { Loader, LoaderError } from "../index.js";

const sha = (s) => createHash("sha256").update(s).digest("hex");

// Laid out like raw.githubusercontent.com/ilang-ai/ilang-spec/<ref>/runtime
class FakeRuntime {
  async start() {
    this.root = mkdtempSync(join(tmpdir(), "ilang-remote-"));
    this.requests = 0;
    this.server = createServer((req, res) => {
      this.requests++;
      try { res.end(readFileSync(join(this.root, decodeURIComponent(req.url)))); }
      catch { res.statusCode = 404; res.end(); }
    });
    await new Promise((ok) => this.server.listen(0, "127.0.0.1", ok));
    this.base = `http://127.0.0.1:${this.server.address().port}/main/runtime`;
    return this;
  }
  put(data, ...parts) {
    const p = join(this.root, ...parts);
    mkdirSync(dirname(p), { recursive: true });
    writeFileSync(p, data);
  }
  publish(version, texts, corrupt) {
    const bundles = {};
    for (const [name, text] of Object.entries(texts)) {
      this.put(corrupt === name ? "tampered" : text, "main", "runtime", `${name}.md`);
      this.put(text, "main", "runtime", "versions", version, `${name}.md`);
      bundles[name] = { url: `${this.base}/${name}.md`, bytes: Buffer.byteLength(text), sha256: sha(text) };
    }
    const manifest = { brand: "iLang", runtime_schema: 1, version, source_commit: `c0ffee${version}`, bundles };
    this.put(JSON.stringify(manifest), "main", "runtime", "manifest.json");
    const pinned = { ...manifest, bundles: Object.fromEntries(Object.entries(bundles).map(([n, b]) =>
      [n, { ...b, url: `${this.base}/versions/${version}/${n}.md` }])) };
    this.put(JSON.stringify(pinned), "main", "runtime", "versions", version, "manifest.json");
  }
  snapshot(commit) {                               // the runtime directory as it is at one commit
    cpSync(join(this.root, "main", "runtime"), join(this.root, commit, "runtime"), { recursive: true });
  }
  async stop() {
    if (this.server.listening) await new Promise((ok) => this.server.close(ok));
  }
}

let remote, cache;
const loader = (ttl = 3600) => new Loader({ runtime: remote.base, cacheDir: cache, ttl, allowCustomSource: true });

beforeEach(async () => {
  remote = await new FakeRuntime().start();
  remote.publish("v1", { core: "CORE ONE", media: "MEDIA ONE" });
  cache = mkdtempSync(join(tmpdir(), "ilang-cache-"));
});
afterEach(async () => {
  await remote.stop();
  rmSync(remote.root, { recursive: true, force: true });
  rmSync(cache, { recursive: true, force: true });
});

describe("loader", () => {
  test("loads, verifies and caches", async () => {
    const ld = loader();
    assert.equal(await ld.load(), "CORE ONE");
    assert.equal(ld.state.source, "remote");
    assert.equal(ld.state.version, "v1");
    assert.equal(readFileSync(join(ld.cache, "latest", "core.md"), "utf8"), "CORE ONE");
    const state = JSON.parse(readFileSync(join(ld.cache, "state.json"), "utf8"));
    assert.deepEqual([state.active_version, state.status, state.source], ["v1", "ok", "remote"]);
  });
  test("within the TTL the network is not used", async () => {
    await loader().load();
    await remote.stop();
    const ld = loader();
    assert.equal(await ld.load(), "CORE ONE");
    assert.equal(ld.state.source, "cache");
  });
  test("remote down after the TTL uses Last Known Good", async () => {
    await loader(0).load();
    await remote.stop();
    const ld = loader(0);
    assert.equal(await ld.load(), "CORE ONE");
    assert.equal(ld.state.source, "cache");
    assert.ok(ld.state.error);
  });
  test("no cache and no network fails open, or throws when strict", async () => {
    await remote.stop();
    const ld = loader();
    assert.equal(await ld.load(), null);
    assert.equal(ld.state.loaded, false);
    await assert.rejects(loader().load({ strict: true }), LoaderError);
  });
  test("a bundle failing its hash never replaces Last Known Good", async () => {
    await loader(0).load();
    remote.publish("v2", { core: "CORE TWO", media: "MEDIA TWO" }, "core");
    const ld = loader(0);
    assert.equal(await ld.load(), "CORE ONE");
    assert.match(ld.state.error, /sha256/);
    assert.equal(readFileSync(join(ld.cache, "latest", "core.md"), "utf8"), "CORE ONE");
  });
  test("a new version replaces the cache", async () => {
    await loader(0).load();
    remote.publish("v2", { core: "CORE TWO", media: "MEDIA TWO" });
    const ld = loader(0);
    assert.equal(await ld.load(), "CORE TWO");
    assert.equal(ld.state.version, "v2");
  });
  test("a pinned version is immutable and works offline", async () => {
    remote.publish("v2", { core: "CORE TWO", media: "MEDIA TWO" });
    assert.equal(await loader().load({ version: "v1" }), "CORE ONE");
    await remote.stop();
    const ld = loader();
    assert.equal(await ld.load({ version: "v1" }), "CORE ONE");
    assert.equal(ld.state.channel, "pinned");
  });
  test("a pinned commit is immutable and works offline", async () => {
    remote.snapshot("abc1234");
    remote.publish("v2", { core: "CORE TWO", media: "MEDIA TWO" });
    assert.equal(await loader().load(), "CORE TWO");
    assert.equal(await loader().load({ commit: "abc1234", extensions: ["media"] }), "CORE ONE\n\nMEDIA ONE");
    await remote.stop();
    const ld = loader();
    assert.equal(await ld.load({ commit: "abc1234" }), "CORE ONE");
    assert.deepEqual([ld.state.channel, ld.state.version], ["pinned", "v1"]);
  });
  test("bad pins and channels are refused", async () => {
    for (const options of [{ channel: "stable" }, { commit: "not-a-sha" }, { commit: "ABC1234" },
      { version: "../v1" }, { version: "v1", commit: "abc1234" }]) {
      await assert.rejects(loader().load(options), Error, JSON.stringify(options));
    }
  });
  test("extensions load on request", async () => {
    assert.equal(await loader().load({ extensions: ["media"] }), "CORE ONE\n\nMEDIA ONE");
  });
  test("only official sources by default", () => {
    assert.throws(() => new Loader({ runtime: "https://example.com/runtime" }));
  });
  test("the default source is the runtime host, with the canon as fallback", () => {
    const ld = new Loader({ cacheDir: cache });
    assert.deepEqual([ld.runtime, ld.fallback],
      ["https://runtime.ilang.app", "https://raw.githubusercontent.com/ilang-ai/ilang-spec/main/runtime"]);
    assert.equal(loader().fallback, null);           // a custom source has no fallback unless given
  });
  test("when the runtime host is down the fallback serves", async () => {
    const dead = await new FakeRuntime().start();
    await dead.stop();
    rmSync(dead.root, { recursive: true, force: true });
    const ld = new Loader({ runtime: dead.base, fallback: remote.base, cacheDir: cache, allowCustomSource: true });
    assert.equal(await ld.load(), "CORE ONE");
    assert.deepEqual([ld.state.source, ld.state.error], ["remote", null]);
    assert.equal(await ld.load({ version: "v1" }), "CORE ONE");
  });
  test("a cached manifest older than the runtime is fetched again", async () => {
    await loader().load();                           // core and the v1 manifest are in the cache
    remote.publish("v2", { core: "CORE TWO", media: "MEDIA TWO" });
    const ld = loader();                             // inside the TTL, so the cached manifest is tried first
    assert.equal(await ld.load({ extensions: ["media"] }), "CORE TWO\n\nMEDIA TWO");
    assert.deepEqual([ld.state.version, ld.state.error], ["v2", null]);
  });
  test("an extension the runtime does not have is refused", async () => {
    await assert.rejects(loader().load({ extensions: ["video"] }), /"video" is not available.*media/);
    await loader().load();                           // the same with the core already in the cache
    await assert.rejects(loader().load({ extensions: ["video"] }), /"video" is not available/);
    await remote.stop();                             // with no source to ask, the loader fails open as before
    assert.equal(await loader().load({ extensions: ["video"] }), null);
  });
  test("a damaged cache file counts as no file", async () => {
    for (const name of ["state.json", join("latest", "manifest.json")]) {
      for (const damage of ["", '{"version": "v1", "bund']) {
        rmSync(cache, { recursive: true, force: true });
        await loader().load();
        const ld = loader();
        writeFileSync(join(ld.cache, name), damage);
        assert.equal(await ld.load(), "CORE ONE", `${name} holding ${JSON.stringify(damage)}`);
        assert.deepEqual([ld.state.source, ld.state.error], ["remote", null]);
        JSON.parse(readFileSync(join(ld.cache, name), "utf8"));   // written again
      }
    }
  });
  test("a cache is tied to its source", async () => {
    const ld = loader();
    assert.equal(await ld.load(), "CORE ONE");       // one source fills the cache directory
    const gone = await new FakeRuntime().start();
    await gone.stop();                               // another source, which does not answer
    rmSync(gone.root, { recursive: true, force: true });
    const other = new Loader({ runtime: gone.base, cacheDir: cache, allowCustomSource: true });
    assert.equal(await other.load(), null);          // what the first source left is not its copy
    const official = new Loader({ cacheDir: cache });
    assert.equal(official.cache, cache);             // the official sources keep the directory itself,
    assert.equal(existsSync(join(official.cache, "latest")), false);   // and nothing else writes there
    const named = new Loader({ runtime: "https://mirror.example/main/runtime", cacheDir: cache, allowCustomSource: true });
    assert.equal(named.cache, join(cache, "sources", "75810265f2ea2d84"));   // as in Python
  });
  test("the timeout is for the whole request", async () => {
    const body = "x".repeat(100);                    // ten seconds at one byte every 0.1 s
    const drip = createServer((req, res) => {
      res.writeHead(200, { "Content-Length": body.length });
      let i = 0;
      const timer = setInterval(() => (i < body.length ? res.write(body[i++]) : res.end()), 100);
      res.on("close", () => clearInterval(timer));   // the loader has hung up
    });
    await new Promise((ok) => drip.listen(0, "127.0.0.1", ok));
    try {
      const ld = new Loader({ runtime: `http://127.0.0.1:${drip.address().port}/main/runtime`, cacheDir: cache,
        allowCustomSource: true, timeoutMs: 500 });
      const started = Date.now();
      assert.equal(await ld.load(), null);
      assert.ok(Date.now() - started < 3000);
      assert.match(ld.state.error, /TimeoutError/);
    } finally {
      await new Promise((ok) => drip.close(ok));
    }
  });
  test("after a failed check the sources are left alone for a while", async () => {
    let ld = loader();
    await ld.load();                                 // a verified copy is on disk
    writeFileSync(join(ld.cache, "state.json"), JSON.stringify({ lastCheck: 1 }));   // and the hourly check is due
    remote.publish("v2", { core: "CORE TWO", media: "MEDIA TWO" }, "core");
    ld = loader();
    remote.requests = 0;
    assert.equal(await ld.load(), "CORE ONE");
    assert.equal(remote.requests, 2);                // the manifest, and the bundle that failed its check
    assert.equal(await ld.load(), "CORE ONE");       // the copy on disk serves and the source is not asked
    assert.equal(remote.requests, 2);
    assert.equal(ld.state.source, "cache");
    assert.match(ld.state.error, /sha256/);
    assert.equal(await ld.load({ extensions: ["media"] }), null);   // no verified copy of this one: the source is asked
    assert.equal(remote.requests, 4);
    assert.equal(await ld.load({ version: "v2" }), "CORE TWO");   // a pin is loaded as usual,
    assert.equal(ld.state.error, null);
    assert.equal(await ld.load(), "CORE ONE");       // and does not end the wait
    assert.equal(remote.requests, 6);
    remote.publish("v2", { core: "CORE TWO", media: "MEDIA TWO" });
    assert.equal(await ld.load(), "CORE ONE");       // still inside the wait
    ld.failed.at = 0;                                // the wait is over
    assert.equal(await ld.load(), "CORE TWO");
    assert.equal(ld.state.error, null);
  });
});

describe("wrap", () => {
  beforeEach(() => ilang.configure({ runtime: remote.base, cacheDir: cache, allowCustomSource: true }));

  test("runtime goes first and the user's messages are untouched", async () => {
    const msgs = [{ role: "system", content: "app rules" }, { role: "user", content: "帮我完成这个任务" }];
    const before = JSON.stringify(msgs);
    const out = await ilang.wrap(msgs);
    assert.equal(JSON.stringify(msgs), before);
    assert.equal(out[0].role, "system");
    assert.match(out[0].content, /<ilang-runtime version="v1">/);
    assert.match(out[0].content, /CORE ONE/);
    assert.deepEqual(out.slice(1), msgs);
  });
  test("mergeSystem puts the runtime before the app system prompt", async () => {
    const msgs = [{ role: "system", content: "app rules" }, { role: "user", content: "hi" }];
    const before = JSON.stringify(msgs);
    const out = await ilang.wrap(msgs, { mergeSystem: true });
    assert.equal(JSON.stringify(msgs), before);
    assert.equal(out.length, 2);
    assert.match(out[0].content, /^You have loaded the official iLang runtime/);
    assert.match(out[0].content, /<\/ilang-runtime>\n\napp rules$/);
    assert.deepEqual(out[1], msgs[1]);
    const parts = await ilang.wrap([{ role: "system", content: [{ type: "text", text: "app rules" }] }], { mergeSystem: true });
    assert.equal(parts[0].content.length, 2);
    assert.match(parts[0].content[0].text, /CORE ONE/);
    const alone = await ilang.wrap([{ role: "user", content: "hi" }], { mergeSystem: true });
    assert.deepEqual(alone.map((m) => m.role), ["system", "user"]);
    assert.deepEqual(await ilang.wrap(out, { mergeSystem: true }), out);   // once only
  });
  test("runtime is added only once", async () => {
    const once = await ilang.wrap([{ role: "user", content: "hi" }]);
    const again = await ilang.wrap([...once, { role: "assistant", content: "ok" }, { role: "user", content: "next" }]);
    assert.equal(again.filter((m) => String(m.content).includes("<ilang-runtime")).length, 1);
  });
  test("messages that carry the runtime are returned without loading", async () => {
    const once = await ilang.wrap([{ role: "user", content: "hi" }]);
    await remote.stop();
    const empty = mkdtempSync(join(tmpdir(), "ilang-empty-"));
    try {
      ilang.configure({ runtime: remote.base, cacheDir: empty, allowCustomSource: true });
      assert.deepEqual(await ilang.wrap(once, { strict: true }), once);   // nothing is loaded, so nothing can fail
      await assert.rejects(ilang.wrap([{ role: "user", content: "hi" }], { strict: true }), LoaderError);
    } finally {
      rmSync(empty, { recursive: true, force: true });
    }
  });
  test("the tag quoted outside a system message does not switch the runtime off", async () => {
    const msgs = [{ role: "user", content: 'what is <ilang-runtime version="v1">?' },
      { role: "assistant", content: [{ type: "text", text: "The <ilang-runtime tag opens it." }] },
      { role: "user", content: "next" }];
    const out = await ilang.wrap(msgs);
    assert.equal(out[0].role, "system");
    assert.match(out[0].content, /CORE ONE/);
    assert.deepEqual(out.slice(1), msgs);
  });
  test("fail-open returns the messages unchanged", async () => {
    await remote.stop();
    ilang.configure({ runtime: remote.base, cacheDir: mkdtempSync(join(tmpdir(), "ilang-empty-")), allowCustomSource: true });
    const msgs = [{ role: "user", content: "hi" }];
    assert.deepEqual(await ilang.wrap(msgs), msgs);
    assert.equal(await ilang.system(), "");
    assert.equal(ilang.status().loaded, false);
  });
  test("status reports version, commit and check time", async () => {
    await ilang.wrap([{ role: "user", content: "hi" }]);
    const s = ilang.status();
    assert.deepEqual([s.brand, s.version, s.commit, s.channel], ["iLang", "v1", "c0ffeev1", "latest"]);
    assert.match(s.lastCheck, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/);
    assert.ok(s.ageSeconds >= 0);
  });
  test("the version in the tag is the version of the text under it", async () => {
    remote.publish("v2", { core: "CORE TWO", media: "MEDIA TWO" });
    await ilang.system();
    await ilang.system({ version: "v1" });           // both are now in the loader's memory
    const [latest, pinned] = await Promise.all([ilang.system(), ilang.system({ version: "v1" })]);   // two calls in flight
    assert.match(latest, /<ilang-runtime version="v2">\nCORE TWO/);
    assert.match(pinned, /<ilang-runtime version="v1">\nCORE ONE/);
  });
});

describe("types", () => {
  test("index.d.ts declares what index.js exports and what Loader accepts", () => {
    const dts = readFileSync(new URL("../index.d.ts", import.meta.url), "utf8");
    for (const name of Object.keys(ilang).filter((n) => n !== "default")) {
      assert.ok(new RegExp(`^export declare (const|class|function) ${name}\\b`, "m").test(dts), name);
    }
    const whole = dts.slice(dts.indexOf("declare const _default"));
    for (const name of Object.keys(ilang.default)) assert.ok(whole.includes(`${name}:`), `default.${name}`);
    const options = dts.slice(dts.indexOf("interface LoaderOptions"), dts.indexOf("interface Status"));
    const accepted = Loader.toString().match(/constructor\(\{([^}]*)\}/)[1].split(",").map((p) => p.split("=")[0].trim());
    assert.ok(accepted.includes("fallback") && accepted.includes("timeoutMs"), accepted.join());
    for (const name of accepted) assert.ok(options.includes(`  ${name}?:`), `LoaderOptions.${name}`);
  });
});

describe("official runtime", { skip: !process.env.ILANG_NETWORK_TESTS }, () => {
  test("the official runtime loads and verifies", async () => {
    const dir = mkdtempSync(join(tmpdir(), "ilang-official-"));
    try {
      const ld = new Loader({ cacheDir: dir });
      const text = await ld.load({ extensions: ["media"], strict: true });
      assert.match(text, /iLang runtime bundle \(core\)/);
      assert.match(text, /iLang runtime bundle \(media\)/);
      assert.equal(ld.state.source, "remote");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
  test("a pinned commit of the official canon loads", async () => {
    const dir = mkdtempSync(join(tmpdir(), "ilang-official-"));
    try {
      const ld = new Loader({ cacheDir: dir });
      assert.match(await ld.load({ commit: "85d1608", strict: true }), /iLang runtime bundle \(core\)/);
      assert.equal(ld.state.version, "2026.09.22-72c06dc60692");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
