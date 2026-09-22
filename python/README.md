# ilang-protocol

**Don't learn iLang. Your AI should.**

The Python loader for [iLang](https://ilang.ai). It fetches the official iLang runtime from the canon repository, checks its sha256, keeps a verified copy on disk and adds it to any model's messages.

```bash
pip install ilang-protocol
```

```python
import ilang

messages = ilang.wrap([{"role": "user", "content": "帮我分析这个问题"}])   # OpenAI-style messages
system = ilang.system()                                                     # Anthropic, Gemini
print(ilang.status())
```

Updates are checked at most once an hour; without a network the last verified copy is used, and with no copy at all the messages go out unchanged unless `strict=True`. Pin an exact runtime with `version=` for reproducible runs; add `extensions=["media"]` for image, video and audio work. The core runtime is about 27,000 tokens, so enable your provider's prompt caching.

Standard library only, Python 3.9+. Source, JavaScript version and documentation: [github.com/ilang-ai/ilang](https://github.com/ilang-ai/ilang). MIT.
