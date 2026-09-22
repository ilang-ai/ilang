# Any OpenAI-compatible endpoint: OpenAI, DeepSeek, Qwen, OpenRouter, your own gateway.
import os

import ilang
from openai import OpenAI

client = OpenAI(api_key=os.environ["API_KEY"], base_url=os.environ.get("BASE_URL"))
messages = ilang.wrap([{"role": "user", "content": "帮我分析这个问题"}])
reply = client.chat.completions.create(model=os.environ["MODEL"], messages=messages)
print(reply.choices[0].message.content)
print(ilang.status())
