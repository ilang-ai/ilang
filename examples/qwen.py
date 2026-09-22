# Qwen through Alibaba Cloud Model Studio in OpenAI-compatible mode. Outside mainland China use
# BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
import os

import ilang
from openai import OpenAI

client = OpenAI(api_key=os.environ["DASHSCOPE_API_KEY"],
                base_url=os.environ.get("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
messages = ilang.wrap([{"role": "user", "content": "帮我分析这个问题"}])
reply = client.chat.completions.create(model=os.environ.get("MODEL", "qwen-plus"), messages=messages)
print(reply.choices[0].message.content)
