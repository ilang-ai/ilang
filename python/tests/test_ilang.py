"""Offline tests: a local HTTP server plays the official runtime. Standard library only.

    python -m unittest discover -s tests          (from the python/ directory)
    ILANG_NETWORK_TESTS=1 ...                     also checks the real official runtime
"""
import contextlib
import hashlib
import http.server
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

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
        self.assertTrue(os.path.exists(os.path.join(ld.cache, "latest", "core.md")))
        with open(os.path.join(ld.cache, "state.json"), encoding="utf-8") as f:
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
        with open(os.path.join(ld.cache, "latest", "core.md"), encoding="utf-8") as f:
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

    def test_the_default_source_is_the_runtime_host_with_the_canon_as_fallback(self):
        ld = Loader(cache_dir=self.cache)
        self.assertEqual(ld.runtime, "https://runtime.ilang.app")
        self.assertEqual(ld.fallback, "https://raw.githubusercontent.com/ilang-ai/ilang-spec/main/runtime")
        self.assertEqual(ld._commit_base("abc1234"),
                         "https://raw.githubusercontent.com/ilang-ai/ilang-spec/abc1234/runtime")
        self.assertIsNone(self.loader().fallback)            # a custom source has no fallback unless given

    def test_when_the_runtime_host_is_down_the_fallback_serves(self):
        dead = FakeRuntime()
        dead.stop()
        ld = Loader(runtime=dead.base, fallback=self.remote.base, cache_dir=self.cache, allow_custom_source=True)
        self.assertEqual(ld.load(), "CORE ONE")
        self.assertEqual((ld.state["source"], ld.state["error"]), ("remote", None))
        self.assertEqual(ld.load(version="v1"), "CORE ONE")

    def test_a_cached_manifest_older_than_the_runtime_is_fetched_again(self):
        self.loader().load()                                  # core and the v1 manifest are in the cache
        self.remote.publish("v2", {"core": "CORE TWO", "media": "MEDIA TWO"})
        ld = self.loader()                                    # inside the TTL, so the cached manifest is tried first
        self.assertEqual(ld.load(extensions=["media"]), "CORE TWO\n\nMEDIA TWO")
        self.assertEqual((ld.state["version"], ld.state["error"]), ("v2", None))

    def test_an_extension_the_runtime_does_not_have_is_refused(self):
        with self.assertRaisesRegex(ValueError, "'video' is not available.*media"):
            self.loader().load(extensions=["video"])
        self.loader().load()                                  # the same with the core already in the cache
        with self.assertRaisesRegex(ValueError, "'video' is not available"):
            self.loader().load(extensions=["video"])
        with self.assertRaisesRegex(ValueError, "'m' is not available"):
            self.loader().load(extensions="media")            # a string where a list is meant
        self.remote.stop()                                    # with no source to ask, the loader fails open as before
        self.assertIsNone(self.loader().load(extensions=["video"]))

    def test_a_damaged_cache_file_counts_as_no_file(self):
        for name in ("state.json", os.path.join("latest", "manifest.json")):
            for damage in (b"", b'{"version": "v1", "bund'):
                with self.subTest(file=name, damage=damage):
                    shutil.rmtree(self.cache, ignore_errors=True)
                    self.loader().load()
                    ld = self.loader()
                    with open(os.path.join(ld.cache, name), "wb") as f:
                        f.write(damage)
                    self.assertEqual(ld.load(), "CORE ONE")
                    self.assertEqual((ld.state["source"], ld.state["error"]), ("remote", None))
                    with open(os.path.join(ld.cache, name), encoding="utf-8") as f:
                        json.load(f)                          # written again

    def test_a_cache_is_tied_to_its_source(self):
        ld = self.loader()
        self.assertEqual(ld.load(), "CORE ONE")               # one source fills the cache directory
        gone = FakeRuntime()
        gone.stop()                                           # another source, which does not answer
        other = Loader(runtime=gone.base, cache_dir=self.cache, allow_custom_source=True)
        self.assertIsNone(other.load())                       # what the first source left is not its copy
        official = Loader(cache_dir=self.cache)
        self.assertEqual(official.cache, self.cache)          # the official sources keep the directory itself,
        self.assertFalse(os.path.exists(os.path.join(official.cache, "latest")))   # and nothing else writes there
        named = Loader(runtime="https://mirror.example/main/runtime", cache_dir=self.cache, allow_custom_source=True)
        self.assertEqual(named.cache, os.path.join(self.cache, "sources", "75810265f2ea2d84"))   # as in JavaScript

    def test_the_timeout_is_for_the_whole_request(self):
        body = b"x" * 100                                     # ten seconds at one byte every 0.1 s

        class Drip(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    for i in range(len(body)):
                        self.wfile.write(body[i:i + 1])
                        self.wfile.flush()
                        time.sleep(0.1)
                except OSError:                               # the loader has hung up
                    pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Drip)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            ld = Loader(runtime="http://127.0.0.1:%d/main/runtime" % server.server_address[1],
                        cache_dir=self.cache, allow_custom_source=True, timeout=0.5)
            started = time.time()
            self.assertIsNone(ld.load())
            self.assertLess(time.time() - started, 3)
            self.assertIn("TimeoutError", ld.state["error"])
        finally:
            server.shutdown()
            server.server_close()

    def test_after_a_failed_check_the_sources_are_left_alone_for_a_while(self):
        ld = self.loader()
        ld.load()                                             # a verified copy is on disk
        with open(os.path.join(ld.cache, "state.json"), "w", encoding="utf-8") as f:
            json.dump({"last_check": 1}, f)                   # and the hourly check is due
        self.remote.publish("v2", {"core": "CORE TWO", "media": "MEDIA TWO"}, corrupt="core")
        ld = self.loader()
        asked = []
        fetch = ld._fetch
        ld._fetch = lambda url: asked.append(url) or fetch(url)
        self.assertEqual(ld.load(), "CORE ONE")
        self.assertEqual(len(asked), 2)                       # the manifest, and the bundle that failed its check
        self.assertEqual(ld.load(), "CORE ONE")               # the copy on disk serves and the source is not asked
        self.assertEqual(len(asked), 2)
        self.assertEqual(ld.state["source"], "cache")
        self.assertIn("sha256", ld.state["error"])
        self.assertIsNone(ld.load(extensions=["media"]))      # no verified copy of this one: the source is asked
        self.assertEqual(len(asked), 4)
        self.assertEqual(ld.load(version="v2"), "CORE TWO")    # a pin is loaded as usual,
        self.assertIsNone(ld.state["error"])
        self.assertEqual(ld.load(), "CORE ONE")               # and does not end the wait
        self.assertEqual(len(asked), 6)
        self.remote.publish("v2", {"core": "CORE TWO", "media": "MEDIA TWO"})
        self.assertEqual(ld.load(), "CORE ONE")               # still inside the wait
        ld._failed = (0, ld._failed[1])                       # the wait is over
        self.assertEqual(ld.load(), "CORE TWO")
        self.assertIsNone(ld.state["error"])


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

    def test_messages_that_carry_the_runtime_are_returned_without_loading(self):
        once = ilang.wrap([{"role": "user", "content": "hi"}])
        self.remote.stop()
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        ilang.configure(runtime=self.remote.base, cache_dir=empty, allow_custom_source=True)
        self.assertEqual(ilang.wrap(once, strict=True), once)   # nothing is loaded, so nothing can fail
        with self.assertRaises(LoaderError):
            ilang.wrap([{"role": "user", "content": "hi"}], strict=True)

    def test_content_parts_are_recognised(self):
        msgs = [{"role": "system", "content": [{"type": "text", "text": "<ilang-runtime version=x>"}]}]
        self.assertEqual(inject(msgs, "block"), msgs)

    def test_the_tag_quoted_outside_a_system_message_does_not_switch_the_runtime_off(self):
        msgs = [{"role": "user", "content": 'what is <ilang-runtime version="v1">?'},
                {"role": "assistant", "content": [{"type": "text", "text": "The <ilang-runtime tag opens it."}]},
                {"role": "user", "content": "next"}]
        out = ilang.wrap(msgs)
        self.assertEqual(out[0]["role"], "system")
        self.assertIn("CORE ONE", out[0]["content"])
        self.assertEqual(out[1:], msgs)

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

    def test_the_version_in_the_tag_is_the_version_of_the_text_under_it(self):
        self.remote.publish("v2", {"core": "CORE TWO"})
        ld = ilang.configure(runtime=self.remote.base, cache_dir=self.cache, allow_custom_source=True)
        ilang.system()
        ilang.system(version="v1")                            # both are now in the loader's memory

        class Shared(dict):                                   # another call's pinned load lands right after
            def update(self, *args, **kwargs):                # this call has written the shared state
                dict.update(self, *args, **kwargs)
                if self["channel"] == "latest":
                    ld.load(version="v1")

        ld.state = Shared(ld.state)
        self.assertIn('<ilang-runtime version="v2">\nCORE TWO', ilang.system())
        self.assertIn('<ilang-runtime version="v1">\nCORE ONE', ilang.system(version="v1"))
        del ld._memo[(("core",), None, None)]                 # latest is loaded afresh, as it is after the TTL
        ilang.system()
        self.assertIn('<ilang-runtime version="v2">\nCORE TWO', ilang.system())   # now served from memory


EXAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "examples", "check_providers.py")


@unittest.skipUnless(os.path.exists(EXAMPLE), "examples/ is not in this copy")
class ExampleTests(unittest.TestCase):
    """examples/check_providers.py against a local gateway."""

    def setUp(self):
        self.remote = FakeRuntime()
        self.remote.publish("v1", {"core": "CORE ONE"})
        self.cache = tempfile.mkdtemp()
        ilang.configure(runtime=self.remote.base, cache_dir=self.cache, allow_custom_source=True)

        class Gateway(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                model = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["model"]
                reply = ({"error": {"message": "provider returned an error", "code": 502}} if model == "model-a" else
                         {"choices": [{"message": {"content": "[READ:@LOCAL|path=report.csv]=>[CNT]=>[OUT]"}}]})
                data = json.dumps(reply).encode()
                self.send_response(200)                       # some gateways report an error this way
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.gateway = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
        threading.Thread(target=self.gateway.serve_forever, daemon=True).start()
        spec = importlib.util.spec_from_file_location("check_providers", EXAMPLE)
        self.example = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.example)

    def tearDown(self):
        self.gateway.shutdown()
        self.gateway.server_close()
        self.remote.stop()
        shutil.rmtree(self.cache, ignore_errors=True)

    def check(self, base, models):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"ILANG_CHECK_BASE_URL": base, "ILANG_CHECK_API_KEY": "test-key"}):
            with contextlib.redirect_stdout(out):
                code = self.example.main(models)
        return code, out.getvalue().splitlines()

    def test_an_error_object_with_http_200_does_not_stop_the_run(self):
        code, lines = self.check("http://127.0.0.1:%d/v1" % self.gateway.server_address[1], ["model-a", "model-b"])
        self.assertEqual(code, 1)
        self.assertRegex(lines[0], r"^FAIL model-a +HTTP 200 .*provider returned an error")
        self.assertRegex(lines[1], r"^ok +model-b +HTTP 200 .*\[READ:@LOCAL")
        self.assertRegex(lines[2], r"^runtime v1 ")

    def test_a_gateway_that_does_not_answer_is_reported_as_a_failure(self):
        base = "http://127.0.0.1:%d/v1" % self.gateway.server_address[1]
        self.gateway.shutdown()
        self.gateway.server_close()
        code, lines = self.check(base, ["model-a"])
        self.assertEqual(code, 1)
        self.assertRegex(lines[0], r"^FAIL model-a +HTTP 0 ")


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
