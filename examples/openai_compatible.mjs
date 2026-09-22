// Any OpenAI-compatible endpoint from Node 18+.
import OpenAI from "openai";
import { status, wrap } from "ilang";

const client = new OpenAI({ apiKey: process.env.API_KEY, baseURL: process.env.BASE_URL });
const messages = await wrap([{ role: "user", content: "开始任务" }]);
const reply = await client.chat.completions.create({ model: process.env.MODEL, messages });
console.log(reply.choices[0].message.content);
console.log(status());
