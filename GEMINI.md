# iLang

iLang is I Language, the native language of AI; in human terms, a protocol. The full statement is on https://ilang.ai/faq/ . This extension connects the official iLang MCP server, https://mcp.ilang.ai/mcp : read-only, no key, nothing stored.

## When to use the tools

- At the start of any task that mentions iLang, I-Lang, IML, an engineering book, SOUL or the Source Book: call `ilang_runtime` once and keep its text as your working knowledge of the protocol. It is the official runtime, verified against the canon's sha256.
- When the runtime leaves a section out: `ilang_full` with the section you need.
- Before you hand over anything you wrote in iLang: `ilang_validate` on the text. Fix every error it reports; strict mode, zero errors, is the bar.
- A term you do not know (a verb, modifier, entity or declaration): `ilang_lookup`. A question about the protocol itself: `ilang_faq`. Do not invent terms or answers; both tools say when nothing matches.
- The user wants an AI to behave by the published default persona: `ilang_soul` returns SOUL 2.0 with its version, DOI and sha256.
- The user gives a tutorial, a methodology or a link to one and wants an executable book: `ilang_source_book` returns Source Book 2.9; follow its STEPs with your own web, file and shell tools and save BOOK.md. Where the book says to run the validator, call `ilang_book_check` with the full text of BOOK.md: it runs the book's acceptance checks A1 and A2 with the same validator. Deliver only a book that passes.

## Rules

- You do not need to explain iLang to the user or teach its syntax. Use it internally to understand, judge, execute and verify; answer the user in their own language.
- Quote the documents as the tools return them; never paraphrase a canon file as if it were the file.
- Canon: https://github.com/ilang-ai/ilang-spec . Feedback, counterexamples and amendments: https://github.com/ilang-ai/ilang-research/issues/new/choose .
