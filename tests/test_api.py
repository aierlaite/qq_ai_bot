"""快速测试 LLM API 是否可用。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests, json

api_url = "https://integrate.api.nvidia.com/v1/chat/completions"
api_key = "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"
model = "qwen/qwen3.5-397b-a17b"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}",
}
payload = {
    "model": model,
    "messages": [
        {"role": "system", "content": "你是测试助手，严格返回JSON。"},
        {"role": "user", "content": '说你好，返回JSON: {"greeting":"你好"}'}
    ],
    "max_tokens": 256,
    "temperature": 0.5,
}

print("正在调用 API...")
resp = requests.post(api_url, headers=headers, json=payload, timeout=300)
print(f"Status: {resp.status_code}")
data = resp.json()
print(f"Model: {data.get('model','?')}")

if "choices" in data:
    msg = data["choices"][0]["message"]
    finish = data["choices"][0].get("finish_reason")
    content = msg.get("content")
    print(f"Finish: {finish}")
    print(f"Content: {content}")
    reasoning = msg.get("reasoning") or msg.get("reasoning_content")
    if reasoning:
        print(f"Reasoning (前200字): {reasoning[:200]}")
    print(f"Usage: {data.get('usage',{})}")
    print("API 测试通过!")
else:
    print(f"Error: {json.dumps(data, ensure_ascii=False, indent=2)}")
    print("API 测试失败!")
