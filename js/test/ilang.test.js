// Offline tests: a local HTTP server plays the official runtime.  node --test test/
// ILANG_NETWORK_TESTS=1 also checks the real official runtime.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterEach, beforeEach, describe, test } from "node:test";
import * as ilang from "../index.js";
import { Loader, LoaderError } from "../index.js";

const sha = (s) => createHash("sha256").update(s).digest("hex");

class FakeRuntime {
  async start() {
    this.root = mkdtempSync(join(tmpdir(), "ilang-remote-"));
    this.server = createServer((req, res) => {
      try { res.end(readFileSync(join(this.root, decodeURIComponent(req.url)))); }
      catch { res.statusCode = 404; res.end(); }
    });
    await new Promise((ok) => this.server.listen(0, "127.0.0.1", ok));
    this.base = `http://127.0.0.1:${this.server.address().port}/runtime`;
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
      this.put(corrupt === name ? "tampered" : text, "runtime", `${name}.md`);
      this.put(text, "runtime", "versions", version, `${name}.md`);
      bundles[name] = { url: `${this.base}/${name}.md`, bytes: Buffer.byteLength(text), sha256: sha(text) };
    }
    const manifest = { brand: "iLang", runtime_schema: 1, version, source_commit: `c0ffee${version}`, bundles };
    this.put(JSON.stringify(manifest), "runtime", "manifest.json");
    const pinned = { ...manifest, bundles: Object.fromEntries(Object.entries(bundles).map(([n, b]) =>
      [n, { ...b, url: `${this.base}/versions/${version}/${n}.md` }])) };
    this.put(JSON.stringify(pinned), "runtime", "versions", version, "manifest.json");
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
    assert.equal(readFileSync(join(cache, "latest", "core.md"), "utf8"), "CORE ONE");
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
    assert.equal(readFileSync(join(cache, "latest", "core.md"), "utf8"), "CORE ONE");
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
    assert.equal(await loader().load({ version: "v1" }), "CORE ONE");
  });
  test("extensions load on request", async () => {
    assert.equal(await loader().load({ extensions: ["media"] }), "CORE ONE\n\nMEDIA ONE");
  });
  test("only official sources by default", () => {
    assert.throws(() => new Loader({ runtime: "https://example.com/runtime" }));
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
  test("runtime is added only once", async () => {
    const once = await ilang.wrap([{ role: "user", content: "hi" }]);
    const again = await ilang.wrap([...once, { role: "assistant", content: "ok" }, { role: "user", content: "next" }]);
    assert.equal(again.filter((m) => String(m.content).includes("<ilang-runtime")).length, 1);
  });
  test("fail-open returns the messages unchanged", async () => {
    await remote.stop();
    ilang.configure({ runtime: remote.base, cacheDir: mkdtempSync(join(tmpdir(), "ilang-empty-")), allowCustomSource: true });
    const msgs = [{ role: "user", content: "hi" }];
    assert.deepEqual(await ilang.wrap(msgs), msgs);
    assert.equal(await ilang.system(), "");
    assert.equal(ilang.status().loaded, false);
  });
  test("status reports version and commit", async () => {
    await ilang.wrap([{ role: "user", content: "hi" }]);
    const s = ilang.status();
    assert.deepEqual([s.brand, s.version, s.sourceCommit], ["iLang", "v1", "c0ffeev1"]);
  });
});

test("the official runtime loads and verifies", { skip: !process.env.ILANG_NETWORK_TESTS }, async () => {
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
