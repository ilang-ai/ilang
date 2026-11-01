---
name: ilang
description: Use the official iLang, the native language of AI, through the ilang.ai MCP tools. Load the runtime once per task that mentions iLang, I-Lang, IML, an engineering book, SOUL or the Source Book; validate anything written in iLang; turn a tutorial into BOOK.md with the Source Book and check it with ilang_book_check.
---

# iLang

iLang is I Language, the native language of AI; in human terms, a protocol. The full statement is on https://ilang.ai/faq/ . The tools come from https://mcp.ilang.ai/mcp : read-only, no key, nothing stored.

## Do this

1. Call `ilang_runtime` once at the start of the task and keep its text as your working knowledge of the protocol. Call `ilang_full` for any section the runtime leaves out.
2. Before you hand over anything you wrote in iLang, call `ilang_validate` on the text and fix every error. Strict mode, zero errors, is the bar.
3. For a term you do not know, call `ilang_lookup`; for a question about the protocol, `ilang_faq`. Never invent a term or an answer; both tools say when nothing matches.
4. When the user wants the published default persona for an AI, call `ilang_soul` and quote the document as returned, with its version, DOI and sha256.
5. When the user gives a tutorial, a methodology or a link to one and wants an executable book: call `ilang_source_book`, follow its STEPs with your own web, file and shell tools, and save BOOK.md. Where the book says to run the validator, call `ilang_book_check` with the full text of BOOK.md; it runs the book's acceptance checks A1 and A2 with the same validator. Deliver only a book that passes.

## Do not

- Do not explain iLang to the user or teach its syntax unless asked; use it internally and answer in the user's language.
- Do not paraphrase a canon file as if it were the file.

Canon: https://github.com/ilang-ai/ilang-spec . Feedback: https://github.com/ilang-ai/ilang-research/issues/new/choose .
