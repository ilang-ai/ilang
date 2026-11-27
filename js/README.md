# ilang-protocol

**Don't learn iLang. Your AI should.**

The JavaScript loader for [iLang](https://ilang.ai). It fetches the official iLang runtime from the canon repository, checks its sha256, keeps a verified copy on disk and adds it to any model's messages.

```bash
npm install ilang-protocol
```

```js
import { wrap, system, status } from "ilang-protocol";

const messages = await wrap([{ role: "user", content: "开始任务" }]);   // OpenAI-style messages
const systemPrompt = await system();                                   // Anthropic, Gemini
console.log(status());
```

Updates are checked at most once an hour; without a network the last verified copy is used, and with no copy at all the messages go out unchanged unless `{ strict: true }`. Pin an exact runtime with `{ version }` for reproducible runs; add `{ extensions: ["media"] }` for image, video and audio work. As of runtime version 2026.11.26-16d02f108a96 the core runtime is 27,498 tokens (cl100k_base, counted on 2026-11-27), so enable your provider's prompt caching.

No dependencies, Node 18+. Source, Python version and documentation: [github.com/ilang-ai/ilang](https://github.com/ilang-ai/ilang). MIT.
