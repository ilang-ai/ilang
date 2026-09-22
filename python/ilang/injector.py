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


def inject(messages, runtime_block, merge_system=False):
    """A new list with the runtime in front; the original messages are never modified.

    By default the runtime is its own first system message, followed by the application's
    messages. For providers that accept a single system message, merge_system=True puts the
    runtime at the start of the application's system message instead. Messages that already
    carry the runtime are returned as they are, so wrapping every turn is safe."""
    messages = list(messages)
    if runtime_block is None or any(_has_runtime(m) for m in messages):
        return messages
    if merge_system:
        for i, m in enumerate(messages):
            if isinstance(m, dict) and m.get("role") == "system":
                content = m.get("content")
                if isinstance(content, list):
                    merged = [{"type": "text", "text": runtime_block}] + content
                else:
                    merged = runtime_block + ("\n\n" + content if content else "")
                messages[i] = dict(m, content=merged)
                return messages
    return [{"role": "system", "content": runtime_block}] + messages
