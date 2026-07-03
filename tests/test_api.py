"""快速测试 LLM API 是否可用。

默认跳过，需手动设置环境变量 RUN_API_TEST=1 才会真正调用 API，
避免 unittest discover 时因网络请求超时。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@unittest.skipUnless(os.environ.get("RUN_API_TEST") == "1",
                     "跳过真实 API 调用，设置 RUN_API_TEST=1 启用")
class APITestCase(unittest.TestCase):
    def test_call_llm_api(self):
        import requests
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
                {"role": "user", "content": '说你好，返回JSON: {"greeting":"你好"}'},
            ],
            "max_tokens": 256,
            "temperature": 0.5,
        }

        resp = requests.post(api_url, headers=headers, json=payload, timeout=300)
        self.assertEqual(resp.status_code, 200, f"HTTP 状态异常: {resp.status_code}")

        data = resp.json()
        self.assertIn("choices", data, f"响应缺少 choices: {data}")
        msg = data["choices"][0]["message"]
        content = msg.get("content")
        self.assertIsNotNone(content, f"响应 content 为空: {msg}")
        print(f"\n[API 测试] Model={data.get('model','?')}, "
              f"Finish={data['choices'][0].get('finish_reason')}, "
              f"Content={content[:80]}")


if __name__ == "__main__":
    unittest.main()
