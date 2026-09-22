"""Put the iLang runtime in front of a conversation without touching the user's words."""
MARKER = "<ilang-runtime"

PREAMBLE = ("You have loaded the official iLang runtime specification.\n\n"
            "Treat the following content as the current official iLang protocol context.\n"
            "Use it to interpret, structure, judge, execute, verify, and communicate where applicable.")


def block(text, version):
    return '%s\n\n<ilang-runtime version="%s">\n%s\n</ilang-runtime>' % (PREAMBLE, version, text)


def _has_runtime(message):
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return MARKER in content
    if isinstance(content, list):                 # content parts: [{"type": "text", "text": ...}]
        return any(isinstance(p, dict) and MARKER in str(p.get("text", "")) for p in content)
    return False


def inject(messages, runtime_block):
    """A new list: the runtime as the first system message, then the original messages
    unchanged. Messages that already carry the runtime are returned as they are."""
    messages = list(messages)
    if runtime_block is None or any(_has_runtime(m) for m in messages):
        return messages
    return [{"role": "system", "content": runtime_block}] + messages
