# DeepSeek through its OpenAI-compatible API.
import os

import ilang
from openai import OpenAI

client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=os.environ.get("BASE_URL", "https://api.deepseek.com"))
messages = ilang.wrap([{"role": "user", "content": "帮我分析这个问题"}])
reply = client.chat.completions.create(model=os.environ.get("MODEL", "deepseek-chat"), messages=messages)
print(reply.choices[0].message.content)
