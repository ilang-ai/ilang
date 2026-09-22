"""Offline tests: a local HTTP server plays the official runtime. Standard library only.

    python -m unittest discover -s tests          (from the python/ directory)
    ILANG_NETWORK_TESTS=1 ...                     also checks the real official runtime
"""
import hashlib
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ilang  # noqa: E402
from ilang.injector import PREAMBLE, inject  # noqa: E402
from ilang.loader import Loader, LoaderError  # noqa: E402


class FakeRuntime:
    """Serves <ref>/runtime/manifest.json, bundles and versions/<v>/ from a temp directory,
    laid out like raw.githubusercontent.com/ilang-ai/ilang-spec/<ref>/runtime."""

    def __init__(self):
        self.root = tempfile.mkdtemp()
        handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=self.root, **k)
        http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.host = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.base = self.host + "/main/runtime"

    def publish(self, version, texts, corrupt=None):
        bundles = {}
        for name, text in texts.items():
            data = text.encode("utf-8")
            self._put(data, "main", "runtime", name + ".md")
            self._put(data, "main", "runtime", "versions", version, name + ".md")
            if corrupt == name:
                self._put(b"tampered", "main", "runtime", name + ".md")
            bundles[name] = {"url": "%s/%s.md" % (self.base, name), "bytes": len(data),
                             "sha256": hashlib.sha256(data).hexdigest()}
        manifest = {"brand": "iLang", "runtime_schema": 1, "version": version,
                    "source_commit": "c0ffee" + version, "bundles": bundles}
        self._put(json.dumps(manifest).encode(), "main", "runtime", "manifest.json")
        pinned = dict(manifest, bundles={n: dict(b, url="%s/versions/%s/%s.md" % (self.base, version, n))
                                         for n, b in bundles.items()})
        self._put(json.dumps(pinned).encode(), "main", "runtime", "versions", version, "manifest.json")

    def snapshot(self, commit):
        """The runtime directory as it is at one commit."""
        shutil.copytree(os.path.join(self.root, "main", "runtime"), os.path.join(self.root, commit, "runtime"))

    def _put(self, data, *parts):
        path = os.path.join(self.root, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.root, ignore_errors=True)


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.remote = FakeRuntime()
        self.remote.publish("v1", {"core": "CORE ONE", "media": "MEDIA ONE"})
        self.cache = tempfile.mkdtemp()

    def tearDown(self):
        self.remote.stop()
        shutil.rmtree(self.cache, ignore_errors=True)

    def loader(self, ttl=3600):
        return Loader(runtime=self.remote.base, cache_dir=self.cache, ttl=ttl, allow_custom_source=True)

    def test_loads_verifies_and_caches(self):
        ld = self.loader()
        self.assertEqual(ld.load(), "CORE ONE")
        self.assertEqual(ld.state["source"], "remote")
        self.assertEqual(ld.state["version"], "v1")
        self.assertTrue(os.path.exists(os.path.join(self.cache, "latest", "core.md")))
        with open(os.path.join(self.cache, "state.json"), encoding="utf-8") as f:
            state = json.load(f)
        self.assertEqual((state["active_version"], state["status"], state["source"]), ("v1", "ok", "remote"))

    def test_within_ttl_the_network_is_not_used(self):
        self.loader().load()
        self.remote.stop()
        ld = self.loader()
        self.assertEqual(ld.load(), "CORE ONE")
        self.assertEqual(ld.state["source"], "cache")

    def test_remote_down_after_ttl_uses_last_known_good(self):
        self.loader(ttl=0).load()
        self.remote.stop()
        ld = self.loader(ttl=0)
        self.assertEqual(ld.load(), "CORE ONE")
        self.assertEqual(ld.state["source"], "cache")
        self.assertIsNotNone(ld.state["error"])

    def test_no_cache_and_no_network_fails_open_or_raises_when_strict(self):
        self.remote.stop()
        ld = self.loader()
        self.assertIsNone(ld.load())
        self.assertFalse(ld.state["loaded"])
        with self.assertRaises(LoaderError):
            self.loader().load(strict=True)

    def test_a_bundle_failing_its_hash_never_replaces_last_known_good(self):
        self.loader(ttl=0).load()
        self.remote.publish("v2", {"core": "CORE TWO", "media": "MEDIA TWO"}, corrupt="core")
        ld = self.loader(ttl=0)
        self.assertEqual(ld.load(), "CORE ONE")
        self.assertIn("sha256", ld.state["error"])
        with open(os.path.join(self.cache, "latest", "core.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "CORE ONE")

    def test_a_new_version_replaces_the_cache(self):
        self.loader(ttl=0).load()
        self.remote.publish("v2", {"core": "CORE TWO", "media": "MEDIA TWO"})
        ld = self.loader(ttl=0)
        self.assertEqual(ld.load(), "CORE TWO")
        self.assertEqual(ld.state["version"], "v2")

    def test_pinned_version_is_immutable_and_works_offline(self):
        self.remote.publish("v2", {"core": "CORE TWO", "media": "MEDIA TWO"})
        self.assertEqual(self.loader().load(version="v1"), "CORE ONE")
        self.remote.stop()
        ld = self.loader()
        self.assertEqual(ld.load(version="v1"), "CORE ONE")
        self.assertEqual(ld.state["channel"], "pinned")

    def test_pinned_commit_is_immutable_and_works_offline(self):
        self.remote.snapshot("abc1234")
        self.remote.publish("v2", {"core": "CORE TWO", "media": "MEDIA TWO"})
        self.assertEqual(self.loader().load(), "CORE TWO")
        self.assertEqual(self.loader().load(commit="abc1234", extensions=["media"]), "CORE ONE\n\nMEDIA ONE")
        self.remote.stop()
        ld = self.loader()
        self.assertEqual(ld.load(commit="abc1234"), "CORE ONE")
        self.assertEqual((ld.state["channel"], ld.state["version"]), ("pinned", "v1"))

    def test_bad_pins_and_channels_are_refused(self):
        ld = self.loader()
        for kwargs in ({"channel": "stable"}, {"commit": "not-a-sha"}, {"commit": "ABC1234"},
                       {"version": "../v1"}, {"version": "v1", "commit": "abc1234"}):
            with self.assertRaises(ValueError, msg=kwargs):
                ld.load(**kwargs)

    def test_extensions_are_loaded_on_request(self):
        self.assertEqual(self.loader().load(extensions=["media"]), "CORE ONE\n\nMEDIA ONE")

    def test_only_official_sources_by_default(self):
        with self.assertRaises(ValueError):
            Loader(runtime="https://example.com/runtime")


class InjectorTests(unittest.TestCase):
    def setUp(self):
        self.remote = FakeRuntime()
        self.remote.publish("v1", {"core": "CORE ONE"})
        self.cache = tempfile.mkdtemp()
        ilang.configure(runtime=self.remote.base, cache_dir=self.cache, allow_custom_source=True)

    def tearDown(self):
        self.remote.stop()
        shutil.rmtree(self.cache, ignore_errors=True)

    def test_runtime_goes_first_and_user_messages_are_untouched(self):
        msgs = [{"role": "system", "content": "app rules"}, {"role": "user", "content": "帮我完成这个任务"}]
        original = json.dumps(msgs)
        out = ilang.wrap(msgs)
        self.assertEqual(json.dumps(msgs), original)          # input not mutated
        self.assertEqual(out[0]["role"], "system")
        self.assertIn('<ilang-runtime version="v1">', out[0]["content"])
        self.assertIn("CORE ONE", out[0]["content"])
        self.assertEqual(out[1:], msgs)

    def test_merge_system_puts_the_runtime_before_the_app_system_prompt(self):
        msgs = [{"role": "system", "content": "app rules"}, {"role": "user", "content": "hi"}]
        original = json.dumps(msgs)
        out = ilang.wrap(msgs, merge_system=True)
        self.assertEqual(json.dumps(msgs), original)
        self.assertEqual(len(out), 2)
        self.assertTrue(out[0]["content"].startswith(PREAMBLE))
        self.assertTrue(out[0]["content"].endswith("</ilang-runtime>\n\napp rules"))
        self.assertEqual(out[1], msgs[1])
        parts = ilang.wrap([{"role": "system", "content": [{"type": "text", "text": "app rules"}]}],
                           merge_system=True)
        self.assertEqual(len(parts[0]["content"]), 2)
        self.assertIn("CORE ONE", parts[0]["content"][0]["text"])
        alone = ilang.wrap([{"role": "user", "content": "hi"}], merge_system=True)
        self.assertEqual([m["role"] for m in alone], ["system", "user"])
        self.assertEqual(ilang.wrap(out, merge_system=True), out)   # once only

    def test_runtime_is_added_only_once(self):
        once = ilang.wrap([{"role": "user", "content": "hi"}])
        again = ilang.wrap(once + [{"role": "assistant", "content": "ok"}, {"role": "user", "content": "next"}])
        self.assertEqual(sum("<ilang-runtime" in m["content"] for m in again), 1)

    def test_content_parts_are_recognised(self):
        msgs = [{"role": "system", "content": [{"type": "text", "text": "<ilang-runtime version=x>"}]}]
        self.assertEqual(inject(msgs, "block"), msgs)

    def test_fail_open_returns_the_messages_unchanged(self):
        self.remote.stop()
        ilang.configure(runtime=self.remote.base, cache_dir=tempfile.mkdtemp(), allow_custom_source=True)
        msgs = [{"role": "user", "content": "hi"}]
        self.assertEqual(ilang.wrap(msgs), msgs)
        self.assertEqual(ilang.system(), "")
        self.assertFalse(ilang.status()["loaded"])

    def test_status_reports_version_commit_and_check_time(self):
        ilang.wrap([{"role": "user", "content": "hi"}])
        s = ilang.status()
        self.assertEqual((s["brand"], s["version"], s["commit"], s["channel"]), ("iLang", "v1", "c0ffeev1", "latest"))
        self.assertRegex(s["last_check"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertGreaterEqual(s["age_seconds"], 0)


@unittest.skipUnless(os.environ.get("ILANG_NETWORK_TESTS"), "set ILANG_NETWORK_TESTS=1")
class OfficialRuntimeTests(unittest.TestCase):
    def test_the_official_runtime_loads_and_verifies(self):
        cache = tempfile.mkdtemp()
        try:
            ld = Loader(cache_dir=cache)
            text = ld.load(extensions=["media"], strict=True)
            self.assertIn("iLang runtime bundle (core)", text)
            self.assertIn("iLang runtime bundle (media)", text)
            self.assertEqual(ld.state["source"], "remote")
        finally:
            shutil.rmtree(cache, ignore_errors=True)

    def test_a_pinned_commit_of_the_official_canon_loads(self):
        cache = tempfile.mkdtemp()
        try:
            ld = Loader(cache_dir=cache)
            self.assertIn("iLang runtime bundle (core)", ld.load(commit="85d1608", strict=True))
            self.assertEqual(ld.state["version"], "2026.09.22-72c06dc60692")
        finally:
            shutil.rmtree(cache, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
