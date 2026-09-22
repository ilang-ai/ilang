"""Send one wrapped request to each model you name and report whether it answered.

    ILANG_CHECK_BASE_URL=https://api.example.com/v1  ILANG_CHECK_API_KEY=...  \
        python examples/check_providers.py deepseek-v4-flash qwen-flash gemini-3.5-flash gpt-4o-mini
    ... python examples/check_providers.py --merge-system qwen-flash         one system message
    ... python examples/check_providers.py --anthropic claude-haiku-4-5      Messages API, ilang.system()

ILANG_CHECK_EXTRA_HEADERS takes a JSON object of extra request headers, for example a gateway's
price cap. Standard library only; run from the repository root with PYTHONPATH=python, or after
pip install ilang-protocol. The key is read from the environment and never printed.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

import ilang

TASK = ("Write one iLang operation chain that reads the file report.csv, keeps the rows whose status "
        "is failed, counts them and outputs the count. Reply with the chain only.")


def post(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers=dict({"Content-Type": "application/json"}, **headers))
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as err:
        return err.code, {"error": err.read().decode("utf-8", "replace")[:300]}


def main(argv):
    base = os.environ["ILANG_CHECK_BASE_URL"].rstrip("/")
    key = os.environ["ILANG_CHECK_API_KEY"]
    extra = json.loads(os.environ.get("ILANG_CHECK_EXTRA_HEADERS", "{}"))
    anthropic, merge = "--anthropic" in argv, "--merge-system" in argv
    models = [a for a in argv if not a.startswith("--")]
    failed = 0
    for model in models:
        started = time.time()
        if anthropic:
            status, reply = post(base + "/messages",
                                 {"model": model, "max_tokens": 1024, "system": ilang.system(),
                                  "messages": [{"role": "user", "content": TASK}]},
                                 dict({"x-api-key": key, "anthropic-version": "2023-06-01"}, **extra))
            text = "".join(p.get("text", "") for p in reply.get("content", []) if isinstance(p, dict))
        else:
            messages = ilang.wrap([{"role": "system", "content": "Answer briefly."},
                                   {"role": "user", "content": TASK}], merge_system=merge)
            status, reply = post(base + "/chat/completions",
                                 {"model": model, "max_tokens": 1024, "messages": messages},
                                 dict({"Authorization": "Bearer " + key}, **extra))
            choice = (reply.get("choices") or [{}])[0]
            text = (choice.get("message") or {}).get("content") or ""
        ok = status == 200 and bool(text.strip())
        failed += not ok
        lines = [l for l in text.strip().splitlines() if l.strip() and not l.startswith("```")]
        first = lines[0][:160] if lines else reply.get("error", "")[:160]
        print("%-4s %-34s HTTP %s  %5.1fs  %s" % ("ok" if ok else "FAIL", model, status, time.time() - started, first))
    s = ilang.status()
    print("runtime %s (commit %s, %s)%s" % (s["version"], s["commit"], s["source"],
                                            "  merge_system" if merge else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
