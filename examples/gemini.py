# Google Gemini: the runtime goes into system_instruction.
import os
from google import genai
from google.genai import types

import ilang

client = genai.Client()
reply = client.models.generate_content(
    model=os.environ["MODEL"],
    contents="帮我分析这个问题",
    config=types.GenerateContentConfig(system_instruction=ilang.system()),
)
print(reply.text)
