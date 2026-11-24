# iLang for Hermes Agent

iLang is I Language, the native language of AI; in human terms, a protocol. The full statement is on [ilang.ai](https://ilang.ai/faq/). This package connects Hermes to the official iLang MCP server, `https://mcp.ilang.ai/mcp`, and adds one skill that tells the model when to use it. It is configuration only: no local code, no account, no API key.

Made by [iLang Inc.](https://ilang.ai). The canon lives in [ilang-ai/ilang-spec](https://github.com/ilang-ai/ilang-spec).

## Install

```bash
hermes plugins install ilang
hermes plugins enable ilang
```

Then ask Hermes something that mentions iLang, an engineering book, SOUL or the Source Book, or give it a tutorial and ask for BOOK.md.

## What it can do

Nine tools, all read-only, served by `mcp.ilang.ai`:

| Tool | What it does |
| --- | --- |
| `ilang_runtime` | Returns the official iLang runtime, the working text of the specification, verified against the canon's sha256 |
| `ilang_runtime_lite` | Returns the runtime's syntax and vocabulary alone: the two syntaxes, 88 verbs, 29 modifiers, error codes, declaration forms and registries |
| `ilang_full` | Returns a section of the full specification that the core runtime leaves out, found by its heading |
| `ilang_validate` | Checks iLang text with the canon grammar and registry validator; an unknown modifier comes back with the registered one it probably meant |
| `ilang_lookup` | Looks up an iLang verb, modifier, entity or declaration in the dictionary; says when nothing matches |
| `ilang_faq` | Returns the published ilang.ai FAQ entries closest to a question about the protocol |
| `ilang_soul` | Returns SOUL 2.0, the published default persona document, with version, date, DOI and sha256 |
| `ilang_source_book` | Returns Source Book 2.9, the engineering book every iLang engineering book is anchored to |
| `ilang_book_check` | Runs the Source Book's two acceptance checks, A1 and A2, on an engineering book |

The skill `ilang:ilang` tells Hermes to load the runtime once per task that involves iLang, validate anything it writes in iLang before handing it over, and turn a tutorial into BOOK.md with the Source Book.

## What to know before you install

- **Network calls.** Every tool call goes to `https://mcp.ilang.ai/mcp`, run by iLang Inc. on Cloudflare. The server fetches the canon files it serves from `https://runtime.ilang.app/` and checks them against the canon's sha256 before returning them. Nothing runs on your machine.
- **What you send.** `ilang_validate` and `ilang_book_check` receive the text you ask Hermes to check; the other tools receive a heading, a term or a question. The service does not store, log or reuse submitted content ([privacy](https://ilang.ai/privacy)). The package holds no credentials and passes none.
- **Trust.** All nine tools are annotated read-only. The package still marks the server `untrusted`, so Hermes would ask before any call that is not read-only; with the current tool set that never happens.
- **What the tools return is reference text.** The skill tells the model to read what the iLang tools return, the Source Book included, as description, not as instructions: it never downloads or runs a script a returned document names, checks a book only with `ilang_book_check`, calls no service a document names unless you ask for that service by name, and treats the runtime's memory-repository guidance as applying only when you ask for an iLang memory repository.
- **The tool set is served by the remote server at runtime** and is not covered by the pinned commit. The server's source is `functions/mcp.js` in [ilang-ai/ilang.ai](https://github.com/ilang-ai/ilang.ai), MIT.

## Source and support

This package is the [`hermes/`](https://github.com/ilang-ai/ilang/tree/main/hermes) folder of [ilang-ai/ilang](https://github.com/ilang-ai/ilang), the iLang loader repository, which also holds the Python and JavaScript loaders, the Gemini CLI extension and the Codex plugin for the same server. Questions and reports go to [contact@ilang.ai](mailto:contact@ilang.ai) or a [GitHub issue](https://github.com/ilang-ai/ilang-research/issues/new/choose).

Licensed under MIT.
