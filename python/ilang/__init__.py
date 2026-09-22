"""iLang loader. Don't learn iLang. Your AI should.

    import ilang
    messages = ilang.wrap(messages)          # OpenAI-style message lists
    system = ilang.system()                  # providers with a separate system field

The loader fetches the official iLang runtime, verifies its sha256, caches it for an
hour, and falls back to the last verified copy when the network is unavailable.
"""
import time

from .injector import block, inject
from .loader import Loader, LoaderError

__version__ = "1.0.0"
__all__ = ["load", "wrap", "system", "status", "configure", "Loader", "LoaderError"]

_loader = None


def configure(**options):
    """Replace the default loader, e.g. configure(cache_dir=..., ttl=...)."""
    global _loader
    _loader = Loader(**options)
    return _loader


def _default():
    return _loader or configure()


def load(extensions=(), version=None, strict=False):
    """Load the runtime now. Returns its text, or None if nothing verified is available."""
    return _default().load(extensions=extensions, version=version, strict=strict)


def system(extensions=(), version=None, strict=False):
    """The runtime as a system-prompt string, or "" when it could not be loaded."""
    text = load(extensions, version, strict)
    return block(text, _default().state["version"]) if text is not None else ""


def wrap(messages, extensions=(), version=None, strict=False):
    """Return messages with the iLang runtime as the first system message.

    The user's messages are never modified, and the runtime is added only once, so
    wrapping every turn of a conversation is safe."""
    text = system(extensions, version, strict)
    return inject(messages, text or None)


def status():
    """What is loaded: version, source commit, where it came from and any last error."""
    s = dict(_default().state, brand="iLang")
    if s.get("last_check"):
        s["age_seconds"] = int(time.time() - s["last_check"])
    return s
