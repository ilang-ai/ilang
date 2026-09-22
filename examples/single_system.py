# Providers or local chat templates that accept only one system message (some self-hosted
# models behind vLLM or Ollama): merge the runtime into your own system prompt.
import os

import ilang
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("API_KEY", "none"), base_url=os.environ["BASE_URL"])
messages = ilang.wrap([{"role": "system", "content": "You are the support assistant of Example Ltd."},
                       {"role": "user", "content": "帮我分析这个问题"}], merge_system=True)
reply = client.chat.completions.create(model=os.environ["MODEL"], messages=messages)
print(reply.choices[0].message.content)
