"""iLang loader. Don't learn iLang. Your AI should.

    import ilang
    messages = ilang.wrap(messages)          # OpenAI-style message lists
    system = ilang.system()                  # providers with a separate system field

The loader fetches the official iLang runtime, verifies its sha256, caches it for an
hour, and falls back to the last verified copy when the network is unavailable.
"""
import time

from .injector import block, inject
from .loader import Loader, LoaderError, iso

__version__ = "1.1.1"
__all__ = ["load", "wrap", "system", "status", "configure", "Loader", "LoaderError"]

_loader = None


def configure(**options):
    """Replace the default loader, e.g. configure(cache_dir=..., ttl=...)."""
    global _loader
    _loader = Loader(**options)
    return _loader


def _default():
    return _loader or configure()


def load(extensions=(), version=None, commit=None, channel="latest", strict=False):
    """Load the runtime now. Returns its text, or None if nothing verified is available.

    version= pins a runtime version such as "2026.09.22-a69b7d69b3a6"; commit= pins the
    runtime as it is at one commit of the canon repository."""
    return _default().load(extensions=extensions, version=version, commit=commit, channel=channel,
                           strict=strict)


def system(extensions=(), version=None, commit=None, channel="latest", strict=False):
    """The runtime as a system-prompt string, or "" when it could not be loaded."""
    text = load(extensions, version, commit, channel, strict)
    return block(text, _default().state["version"]) if text is not None else ""


def wrap(messages, extensions=(), version=None, commit=None, channel="latest", strict=False,
         merge_system=False):
    """Return messages with the iLang runtime in front.

    The runtime is the first system message; with merge_system=True it is put at the start
    of the application's system message, for providers that accept only one. The user's
    messages are never modified, and the runtime is added only once, so wrapping every turn
    of a conversation is safe."""
    text = system(extensions, version, commit, channel, strict)
    return inject(messages, text or None, merge_system=merge_system)


def status():
    """What is loaded: version, commit, where it came from, cache age and any last error."""
    state = _default().state
    s = dict(state, brand="iLang", commit=state["source_commit"], last_check=iso(state["last_check"]))
    if state.get("last_check"):
        s["age_seconds"] = int(time.time() - state["last_check"])
    return s
