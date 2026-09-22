# iLang

**Don't learn iLang. Your AI should.**

[![PyPI](https://img.shields.io/pypi/v/ilang-protocol?label=pip%20install%20ilang-protocol)](https://pypi.org/project/ilang-protocol/) [![npm](https://img.shields.io/npm/v/ilang-protocol?label=npm%20install%20ilang-protocol)](https://www.npmjs.com/package/ilang-protocol) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22899027.svg)](https://doi.org/10.5281/zenodo.22899027)

iLang is a protocol for AI, not a language for people to memorise. You keep saying what you want in your own words: your goals, your conditions, what may and may not be done. The AI reads iLang, writes it, checks it and works by it.

This repository is the loader that gives any model the official iLang. It fetches the current runtime from the [iLang canon](https://github.com/ilang-ai/ilang-spec), checks its sha256, keeps a verified copy on disk and puts it in front of the model's context. It does not implement iLang, does not change what you or your users write, and does not care which model you call.

## Use it now

**You chat with an AI.** Paste this into ChatGPT, Claude, Gemini, DeepSeek, Qwen or any other assistant, followed by the runtime from [ilang-latest.md](https://raw.githubusercontent.com/ilang-ai/ilang-spec/main/runtime/ilang-latest.md):

```text
Please load and use the official iLang runtime below. You do not need to explain iLang to me
or teach me its syntax. From the next task on, use it internally to understand, judge,
execute and verify.
```

**You build with an API.** Install the loader and wrap your messages:

```bash
pip install ilang-protocol
```

```python
import ilang

messages = ilang.wrap([{"role": "user", "content": "帮我分析这个问题"}])
# send messages to any OpenAI-compatible endpoint: OpenAI, DeepSeek, Qwen, OpenRouter, your gateway
```

```bash
npm install ilang-protocol
```

```js
import { wrap } from "ilang-protocol";

const messages = await wrap([{ role: "user", content: "开始任务" }]);
```

Providers that take the system prompt as a separate field, such as Anthropic and Gemini, use `ilang.system()` instead of `wrap()`. Providers and chat templates that accept only one system message take `merge_system=True`. See [examples](examples/): OpenAI-compatible, DeepSeek, Qwen, Gemini, Claude and a single system message.

## What it does

1. Reads the official [runtime manifest](https://raw.githubusercontent.com/ilang-ai/ilang-spec/main/runtime/manifest.json) at most once an hour.
2. Downloads a bundle only when its sha256 changes, and accepts it only if the sha256 matches.
3. Keeps the last verified copy on disk. If the network or GitHub is down, it keeps working from that copy.
4. Adds the runtime as the first system message, once. Your own system prompt and your users' messages stay exactly as they were, so wrapping every turn of a conversation is safe.

The runtime itself is generated in the canon repository from the specification files and never edited by hand, so there is one source of truth and no second copy of the rules anywhere in this package.

## Options

```python
ilang.wrap(messages, extensions=["media"])                # add the image, video and audio vocabulary
ilang.wrap(messages, version="2026.09.22-a69b7d69b3a6")   # pin an exact runtime for reproducible runs
ilang.wrap(messages, commit="85d1608")                    # or pin the runtime as it is at one canon commit
ilang.wrap(messages, merge_system=True)                   # one system message: the runtime, then your prompt
ilang.wrap(messages, strict=True)                         # raise instead of failing open
ilang.status()                                            # version, commit, channel, cache age, last error
```

The JavaScript API takes the same options as an object: `wrap(messages, { extensions, version, commit, mergeSystem, strict })`.

| Behaviour | Default |
|---|---|
| Update check | once per hour (`ttl=3600`) |
| Channel | `latest`; pin instead with `version=` or `commit=`, both immutable and served from disk after the first load |
| System messages | the runtime is its own first system message; `merge_system=True` puts it at the start of yours instead |
| Cache | `~/.cache/ilang`, or `ILANG_CACHE_DIR` |
| No network, no cache | fail open: messages are sent unchanged; `strict=True` raises instead |
| Sources | official only: `raw.githubusercontent.com/ilang-ai/`, `github.com/ilang-ai/`, `ilang.ai`. A custom source needs `allow_custom_source=True` in code; nothing in a prompt can change it |

**Size.** The core runtime is about 18,600 tokens (cl100k): the working text of the three core documents, with version histories, the formal declaration grammar and most worked examples left out. Its header lists what was left out and points the model to the full text, [ilang.ai/runtime/full](https://ilang.ai/runtime/full), for anything it is unsure about. The media extension adds about 18,000 tokens. Every wrapped request carries the runtime, so turn on your provider's prompt caching where it has one.

## Checked with real models

On 23 September 2026 each of these models got the current core runtime through the loader and two requests. First, an iLang operation chain that reads `report.csv`, keeps the failed rows, counts them and outputs the count: every model answered with a chain that passes the canon grammar validator with no error or warning. Second, a question about a part the core bundle leaves out, the eight declaration body forms: every model said the section was not loaded and pointed to it instead of guessing.

| Model | API | Chain |
|---|---|---|
| gpt-6-astra | OpenAI-compatible | `[READ:@LOCAL\|path=report.csv]=>[PARS\|fmt=csv]=>[FILT\|whr="status == failed"]=>[CNT]=>[OUT]` |
| gemini-3.8-flash | OpenAI-compatible | `[READ:@LOCAL\|path=report.csv]=>[FILT\|whr="status=failed"]=>[CNT]=>[OUT]` |
| deepseek-v4.1-flash | OpenAI-compatible | `[READ:@LOCAL\|path=report.csv\|fmt=csv]=>[FILT\|whr="status=failed"]=>[CNT]=>[OUT]` |
| qwen3.8-max | OpenAI-compatible | `[READ:@LOCAL\|path=report.csv\|fmt=csv]=>[FILT\|whr=status=failed]=>[CNT]=>[OUT]` |
| kimi-k3 | OpenAI-compatible | `[READ:@LOCAL\|path=report.csv]=>[FILT\|whr="status=failed"]=>[CNT]=>[OUT]` |
| claude-fable-5.1 | Anthropic Messages, `ilang.system()` | `[READ:@LOCAL\|path=report.csv]=>[FILT\|whr="status=failed"]=>[CNT]=>[OUT]` |

This shows that each provider takes the wrapped request; how well a model follows iLang across the whole protocol is what the conformance suite measures. Run the chain check against your own endpoint with [examples/check_providers.py](examples/check_providers.py).

## Pinning for research

Every runtime version is kept under its own immutable path in the canon repository. Pin one with `version=` and a benchmark, an audit or a paper can be re-run against exactly the context it used. `ilang.status()` reports the version and the canon commit in use.

What loading the runtime does and does not achieve is measured, not assumed: see the [iLang conformance results](https://research.ilang.ai/datasets/ilang-conformance/) and the preprint [*The Missing Definition of Right*](https://doi.org/10.5281/zenodo.22882691).

## Citation

[CITATION.cff](CITATION.cff); Zenodo archives each release. Concept DOI [10.5281/zenodo.22899027](https://doi.org/10.5281/zenodo.22899027) (all versions).

## License

MIT
