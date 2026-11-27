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
RETRY = 60                                # seconds the sources are left alone after a check that failed
AGENT = "ilang-loader-python/1.1.5"
CHANNELS = ("latest",)
_COMMIT = re.compile(r"[0-9a-f]{7,40}")
_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.\-]*")


class LoaderError(RuntimeError):
    pass


class _UnknownExtension(Exception):
    """An extension name the manifest in hand does not have. load() raises it to the caller as a
    ValueError, like a wrong channel."""


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _origin(url):
    parts = urllib.parse.urlsplit(url)
    return "%s://%s/" % (parts.scheme, parts.netloc)


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else None


class Loader:
    def __init__(self, runtime=RUNTIME, cache_dir=None, ttl=TTL, allow_custom_source=False, fallback=None,
                 timeout=TIMEOUT):
        """timeout, in seconds, bounds the reading of the body and each wait for the connection and
        the headers; timeoutMs, in milliseconds, bounds the whole request in JavaScript."""
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
        if (self.runtime, self.fallback) != (RUNTIME, FALLBACK):
            # A cache belongs to its source. Any other source keeps its files in a directory of its own,
            # so the official loader never serves what another source left. JavaScript uses the same name.
            source = "%s\n%s" % (self.runtime, self.fallback or "")
            self.cache = os.path.join(self.cache, "sources", _sha(source.encode("utf-8"))[:16])
        self.ttl = ttl
        self.timeout = timeout
        self._failed = None                       # (time, error) of the last check that failed
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
        deadline = time.monotonic() + self.timeout    # one limit for the body as a whole, as in JavaScript;
        chunks = []                                   # urlopen's own timeout limits each wait, not their sum
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            read = getattr(r, "read1", r.read)        # read1 returns what has arrived instead of waiting for all
            while True:
                chunk = read(65536)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
                if time.monotonic() > deadline:
                    raise TimeoutError("%s: no complete answer within %s seconds" % (url, self.timeout))

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
        try:
            state = json.loads(raw)                # the JavaScript loader writes lastCheck
            return state.get("last_check") or state.get("lastCheck") or 0
        except (ValueError, AttributeError):      # a damaged file counts as no file
            return 0

    def _get(self, manifest, name, where, remote, base=None):
        """One bundle, verified against the manifest; (bytes, came_from_network)."""
        meta = manifest["bundles"].get(name)
        if meta is None and name != "core":
            raise _UnknownExtension("extension %r is not available; use a list of the names this runtime has: %s"
                                    % (name, ", ".join(sorted(b for b in manifest["bundles"] if b != "core"))))
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
        try:
            manifest = json.loads(cached) if cached else None
        except ValueError:                        # a damaged file counts as no file: it is fetched again
            manifest = None
        checked = False
        source_dir = runtime or self.runtime
        base = (self._commit_base(commit) if commit else
                "%s/versions/%s" % (source_dir, version) if version else source_dir)
        if manifest is None or (not pinned and time.time() - self._last_check() >= self.ttl):
            manifest, checked = json.loads(self._fetch(base + "/manifest.json")), True
        try:
            got = [self._get(manifest, n, where, True, base) for n in names]
        except (LoaderError, _UnknownExtension):
            if checked:
                raise
            # The manifest came from the cache and may be older than the runtime: fetch it once.
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

    def _last_known_good(self, names, version, commit):
        """The verified copy on disk as (manifest, texts), or None. Never the network."""
        try:
            where = self._where(version, commit)
            manifest = json.loads(self._read(*where, "manifest.json") or b"null")
            return manifest, [self._get(manifest, n, where, False)[0].decode("utf-8") for n in names]
        except Exception:
            return None

    def load(self, extensions=(), version=None, commit=None, channel="latest", strict=False):
        """The runtime text, or None when nothing verified is available and strict is off.

        version= or commit= pins an exact runtime; both are immutable, so a pinned runtime is
        fetched once and then served from disk."""
        return self._text_and_version(extensions, version, commit, channel, strict)[0]

    def _text_and_version(self, extensions, version, commit, channel, strict):
        """load(), with the version of the text it returns. A caller that labels the text takes
        the version from here: self.state is shared, and another call may have written it since."""
        if channel not in CHANNELS:
            raise ValueError("channel %r is not available; use 'latest', or pin with version= or commit="
                             % (channel,))
        if version and commit:
            raise ValueError("pin with version= or commit=, not both")
        if commit is not None and not _COMMIT.fullmatch(commit):
            raise ValueError("commit must be 7 to 40 lowercase hex characters")
        if version is not None and not _VERSION.fullmatch(version):
            raise ValueError("version must look like 2026.11.19-105ffdc14ac2")
        names = ["core"] + [e for e in extensions if e != "core"]
        key = (tuple(names), version, commit)
        hit = self._memo.get(key)
        if hit and (version or commit or time.time() - hit[1] < self.ttl):
            self.state.update(hit[2])
            return hit[0], hit[2]["version"]
        latest = not version and not commit       # a pin on disk is served without the network anyway
        failed = self._failed if latest else None
        good = None
        if failed and time.time() - failed[0] < min(RETRY, self.ttl):
            # A check has just failed. While a verified copy is on disk it serves and the sources are left
            # alone, so that sources which hang do not cost every call their timeouts.
            good = self._last_known_good(names, version, commit)
        if good is not None:
            error = failed[1]
        else:
            try:
                manifest, texts, source = self._load(names, version, commit)
                error = None
            except _UnknownExtension as err:      # the caller's mistake, like a wrong channel
                raise ValueError(str(err)) from None
            except Exception as err:              # network, hash or parse failure
                error = "%s: %s" % (type(err).__name__, err)
                if self.fallback and not commit:  # a commit is already read from the canon
                    try:
                        manifest, texts, source = self._load(names, version, commit, self.fallback)
                        error = None
                    except _UnknownExtension as err2:
                        raise ValueError(str(err2)) from None
                    except Exception as err2:
                        error += "; fallback %s: %s" % (type(err2).__name__, err2)
            if latest:
                self._failed = None if error is None else (time.time(), error)
            if error is not None:
                good = self._last_known_good(names, version, commit)
        self.state["error"] = error
        if good is not None:
            manifest, texts, source = good[0], good[1], "cache"
        elif error is not None:
            if strict:
                raise LoaderError(error)
            self.state.update(loaded=False, source="none")
            return None, None
        # This load's own values, kept with its text: self.state is shared and may have been written since.
        loaded = {"loaded": True, "source": source, "version": manifest["version"],
                  "channel": "pinned" if version or commit else "latest",
                  "source_commit": manifest["source_commit"]}
        self.state.update(loaded, last_check=self._last_check() or None)
        text = "\n\n".join(texts)
        if error is None:                         # a Last Known Good copy is not kept in memory: the sources
            self._memo[key] = (text, time.time(), loaded)   # are asked again once RETRY seconds have passed
        return text, manifest["version"]
