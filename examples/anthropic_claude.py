# Providers with a separate system field: pass ilang.system() there.
import anthropic
import ilang

client = anthropic.Anthropic()
reply = client.messages.create(
    model="claude-opus-5",
    max_tokens=2048,
    system=ilang.system() + "\n\nYour application's own system prompt goes here.",
    messages=[{"role": "user", "content": "帮我分析这个问题"}],
)
print(reply.content[0].text)
