"""Fetch the official iLang runtime, verify it, and keep a Last Known Good copy on disk."""
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request

RUNTIME = "https://runtime.ilang.app"
FALLBACK = "https://raw.githubusercontent.com/ilang-ai/ilang-spec/main/runtime"   # the canon itself
CANON = "https://raw.githubusercontent.com/ilang-ai/ilang-spec/%s/runtime"       # the canon at one commit
OFFICIAL = ("https://runtime.ilang.app/", "https://raw.githubusercontent.com/ilang-ai/",
            "https://github.com/ilang-ai/", "https://ilang.ai/")
TTL = 3600
TIMEOUT = 10
AGENT = "ilang-loader-python/1.1.0"
CHANNELS = ("latest",)
_COMMIT = re.compile(r"[0-9a-f]{7,40}")
_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.\-]*")


class LoaderError(RuntimeError):
    pass


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _origin(url):
    parts = urllib.parse.urlsplit(url)
    return "%s://%s/" % (parts.scheme, parts.netloc)


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else None


class Loader:
    def __init__(self, runtime=RUNTIME, cache_dir=None, ttl=TTL, allow_custom_source=False, fallback=None):
        if fallback is None and runtime.rstrip("/") == RUNTIME:
            fallback = FALLBACK                   # the canon repository, when the runtime host is down
        for url in (runtime, fallback or runtime):
            if not (url.rstrip("/") + "/").startswith(OFFICIAL) and not allow_custom_source:
                raise ValueError("iLang loads only from official sources unless allow_custom_source=True")
        self.runtime = runtime.rstrip("/")
        self.fallback = fallback.rstrip("/") if fallback else None
        if self.fallback == self.runtime:
            self.fallback = None
        self._origins = tuple(_origin(u) for u in (self.runtime, self.fallback) if u)
        self._custom = allow_custom_source
        self.cache = cache_dir or os.environ.get("ILANG_CACHE_DIR") or os.path.join(
            os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "ilang")
        self.ttl = ttl
        self.state = {"loaded": False, "channel": "latest", "source": "none", "version": None,
                      "source_commit": None, "last_check": None, "error": None}
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
        if not url.startswith(OFFICIAL) and not (self._custom and url.startswith(self._origins)):
            raise LoaderError("refusing to fetch from %s" % url)
        req = urllib.request.Request(url, headers={"User-Agent": AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read()

    def _commit_base(self, commit):
        """The runtime directory as it is at one commit. The runtime host serves only the current
        canon, so a commit is read from the canon repository; any other source is laid out like
        .../<ref>/runtime and has its ref replaced."""
        if self.runtime == RUNTIME:
            return CANON % commit
        ref_dir = self.runtime[:-len("/runtime")] if self.runtime.endswith("/runtime") else self.runtime
        return ref_dir.rsplit("/", 1)[0] + "/" + commit + "/runtime"

    def _last_check(self):
        raw = self._read("state.json")
        if not raw:
            return 0
        state = json.loads(raw)                    # the JavaScript loader writes lastCheck
        return state.get("last_check") or state.get("lastCheck") or 0

    def _get(self, manifest, name, where, remote, base=None):
        """One bundle, verified against the manifest; (bytes, came_from_network)."""
        meta = manifest["bundles"].get(name)
        if meta is None:
            raise LoaderError("the runtime has no bundle named %r" % name)
        data = self._read(*where, name + ".md")
        if data is not None and _sha(data) == meta["sha256"]:
            return data, False
        if not remote:
            raise LoaderError("no verified %s bundle in the cache" % name)
        url = base + "/" + meta["url"].rsplit("/", 1)[1] if base else meta["url"]
        data = self._fetch(url)
        if len(data) != meta["bytes"] or _sha(data) != meta["sha256"]:
            raise LoaderError("the %s bundle failed its sha256 check" % name)
        return data, True

    @staticmethod
    def _where(version, commit):
        return ("commits", commit) if commit else ("versions", version) if version else ("latest",)

    def _load(self, names, version, commit, runtime=None):
        """Load from one source: the runtime host by default, or the fallback."""
        where = self._where(version, commit)
        pinned = bool(version or commit)
        cached = self._read(*where, "manifest.json")
        manifest = json.loads(cached) if cached else None
        checked = False
        source_dir = runtime or self.runtime
        base = (self._commit_base(commit) if commit else
                "%s/versions/%s" % (source_dir, version) if version else source_dir)
        if manifest is None or (not pinned and time.time() - self._last_check() >= self.ttl):
            manifest, checked = json.loads(self._fetch(base + "/manifest.json")), True
        got = [self._get(manifest, n, where, True, base) for n in names]
        for n, (data, new) in zip(names, got):   # write only once everything has verified
            if new:
                self._write(data, *where, n + ".md")
        if checked:
            self._write(json.dumps(manifest).encode(), *where, "manifest.json")
            if not pinned:
                now = time.time()
                self._write(json.dumps({"last_check": now, "last_check_at": iso(now), "last_success_at": iso(now),
                                        "active_version": manifest["version"], "source": "remote",
                                        "status": "ok"}).encode(), "state.json")
        source = "remote" if checked or any(new for _, new in got) else "cache"
        return manifest, [data.decode("utf-8") for data, _ in got], source

    def load(self, extensions=(), version=None, commit=None, channel="latest", strict=False):
        """The runtime text, or None when nothing verified is available and strict is off.

        version= or commit= pins an exact runtime; both are immutable, so a pinned runtime is
        fetched once and then served from disk."""
        if channel not in CHANNELS:
            raise ValueError("channel %r is not available; use 'latest', or pin with version= or commit="
                             % (channel,))
        if version and commit:
            raise ValueError("pin with version= or commit=, not both")
        if commit is not None and not _COMMIT.fullmatch(commit):
            raise ValueError("commit must be 7 to 40 lowercase hex characters")
        if version is not None and not _VERSION.fullmatch(version):
            raise ValueError("version must look like 2026.09.22-a69b7d69b3a6")
        names = ["core"] + [e for e in extensions if e != "core"]
        key = (tuple(names), version, commit)
        hit = self._memo.get(key)
        if hit and (version or commit or time.time() - hit[1] < self.ttl):
            self.state.update(hit[2])
            return hit[0]
        try:
            manifest, texts, source = self._load(names, version, commit)
            self.state["error"] = None
        except Exception as err:                  # network, hash or parse failure
            self.state["error"] = "%s: %s" % (type(err).__name__, err)
            if self.fallback and not commit:      # a commit is already read from the canon
                try:
                    manifest, texts, source = self._load(names, version, commit, self.fallback)
                    self.state["error"] = None
                except Exception as err2:
                    self.state["error"] += "; fallback %s: %s" % (type(err2).__name__, err2)
        if self.state["error"] is not None:
            try:                                  # Last Known Good, never the network
                where = self._where(version, commit)
                manifest = json.loads(self._read(*where, "manifest.json") or b"null")
                texts = [self._get(manifest, n, where, False)[0].decode("utf-8") for n in names]
                source = "cache"
            except Exception:
                if strict:
                    raise LoaderError(self.state["error"])
                self.state.update(loaded=False, source="none")
                return None
        self.state.update(loaded=True, source=source, version=manifest["version"],
                          channel="pinned" if version or commit else "latest",
                          source_commit=manifest["source_commit"],
                          last_check=self._last_check() or None)
        text = "\n\n".join(texts)
        if self.state["error"] is None:           # a fallback copy is re-checked next call
            self._memo[key] = (text, time.time(), {k: self.state[k] for k in
                                                    ("loaded", "channel", "source", "version", "source_commit")})
        return text
