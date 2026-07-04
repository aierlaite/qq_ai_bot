"""快速测试 LLM API 是否可用。

直接运行：python tests/test_api.py
被 unittest 发现时不执行（避免 import 时发真实 API 请求）。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run_api_test():
    import requests, json
    import yaml

    with open("config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    api_url = cfg["llm"]["api_url"]
    api_key = cfg["llm"]["api_key"]
    model = cfg["llm"]["model"]

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


if __name__ == "__main__":
    _run_api_test()
