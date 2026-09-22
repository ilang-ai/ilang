"""Fetch the official iLang runtime, verify it, and keep a Last Known Good copy on disk."""
import hashlib
import json
import os
import tempfile
import time
import urllib.request

RUNTIME = "https://raw.githubusercontent.com/ilang-ai/ilang-spec/main/runtime"
OFFICIAL = ("https://raw.githubusercontent.com/ilang-ai/", "https://github.com/ilang-ai/",
            "https://ilang.ai/")
TTL = 3600
TIMEOUT = 10
AGENT = "ilang-loader-python/1.0.1"


class LoaderError(RuntimeError):
    pass


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class Loader:
    def __init__(self, runtime=RUNTIME, cache_dir=None, ttl=TTL, allow_custom_source=False):
        if not runtime.startswith(OFFICIAL) and not allow_custom_source:
            raise ValueError("iLang loads only from official sources unless allow_custom_source=True")
        self.runtime = runtime.rstrip("/")
        self.cache = cache_dir or os.environ.get("ILANG_CACHE_DIR") or os.path.join(
            os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "ilang")
        self.ttl = ttl
        self.state = {"loaded": False, "source": "none", "version": None, "source_commit": None,
                      "last_check": None, "error": None}
        self._memo = {}

    def _read(self, *parts):
        try:
            with open(os.path.join(self.cache, *parts), "rb") as f:
                return f.read()
        except OSError:
            return None

    def _write(self, data, *parts):
        path = os.path.join(self.cache, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)                     # atomic: a reader never sees half a file

    def _fetch(self, url):
        if not url.startswith(OFFICIAL) and not url.startswith(self.runtime):
            raise LoaderError("refusing to fetch from %s" % url)
        req = urllib.request.Request(url, headers={"User-Agent": AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read()

    def _last_check(self):
        raw = self._read("state.json")
        return json.loads(raw).get("last_check", 0) if raw else 0

    def _get(self, manifest, name, where, remote):
        """One bundle, verified against the manifest; (bytes, came_from_network)."""
        meta = manifest["bundles"].get(name)
        if meta is None:
            raise LoaderError("the runtime has no bundle named %r" % name)
        data = self._read(*where, name + ".md")
        if data is not None and _sha(data) == meta["sha256"]:
            return data, False
        if not remote:
            raise LoaderError("no verified %s bundle in the cache" % name)
        data = self._fetch(meta["url"])
        if len(data) != meta["bytes"] or _sha(data) != meta["sha256"]:
            raise LoaderError("the %s bundle failed its sha256 check" % name)
        return data, True

    def _load(self, names, version):
        where = ("versions", version) if version else ("latest",)
        cached = self._read(*where, "manifest.json")
        manifest = json.loads(cached) if cached else None
        checked = False
        if manifest is None or (not version and time.time() - self._last_check() >= self.ttl):
            url = "%s/versions/%s/manifest.json" % (self.runtime, version) if version else \
                self.runtime + "/manifest.json"
            manifest, checked = json.loads(self._fetch(url)), True
        got = [self._get(manifest, n, where, True) for n in names]
        for n, (data, new) in zip(names, got):   # write only once everything has verified
            if new:
                self._write(data, *where, n + ".md")
        if checked:
            self._write(json.dumps(manifest).encode(), *where, "manifest.json")
            if not version:
                self._write(json.dumps({"last_check": time.time()}).encode(), "state.json")
        source = "remote" if checked or any(new for _, new in got) else "cache"
        return manifest, [data.decode("utf-8") for data, _ in got], source

    def load(self, extensions=(), version=None, strict=False):
        """The runtime text, or None when nothing verified is available and strict is off."""
        names = ["core"] + [e for e in extensions if e != "core"]
        key = (tuple(names), version)
        hit = self._memo.get(key)
        if hit and (version or time.time() - hit[1] < self.ttl):
            self.state.update(hit[2])
            return hit[0]
        try:
            manifest, texts, source = self._load(names, version)
            self.state["error"] = None
        except Exception as err:                  # network, hash or parse failure
            self.state["error"] = "%s: %s" % (type(err).__name__, err)
            try:                                  # Last Known Good, never the network
                where = ("versions", version) if version else ("latest",)
                manifest = json.loads(self._read(*where, "manifest.json") or b"null")
                texts = [self._get(manifest, n, where, False)[0].decode("utf-8") for n in names]
                source = "cache"
            except Exception:
                if strict:
                    raise LoaderError(self.state["error"])
                self.state.update(loaded=False, source="none")
                return None
        self.state.update(loaded=True, source=source, version=manifest["version"],
                          source_commit=manifest["source_commit"],
                          last_check=self._last_check() or None)
        text = "\n\n".join(texts)
        if self.state["error"] is None:           # a fallback copy is re-checked next call
            self._memo[key] = (text, time.time(), {k: self.state[k] for k in
                                                    ("loaded", "source", "version", "source_commit")})
        return text
