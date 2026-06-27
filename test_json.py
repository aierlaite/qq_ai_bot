import json

raw = '''{
  "thought": "（…突然问起游戏，是在转移话题吗？刚才的"吃 47"还没解释清楚呢。不过看他这么认真地在问，应该是看到了什么有趣的东西吧。稍微有点好奇他指的是哪个游戏呐）",
  "action": "reply",
  "targets": ["忆雨"],
  "messages": [
    "…是指刚才发的图片吗？",
    "还是说，你在玩什么新游戏呀？",
    " 笨蛋，别总是突然换话题嘛。"
  ],
  "affinity_delta": {"169372827": 1}
}'''

print("长度:", len(raw))
print("尝试解析...")
try:
    result = json.loads(raw)
    print("✓ 解析成功")
    print("thought:", result["thought"][:50])
except Exception as e:
    print("✗ 解析失败:", e)

# 尝试处理中文引号
print("\n尝试替换中文引号...")
fixed = raw.replace('"', '"').replace('"', '"')
try:
    result = json.loads(fixed)
    print("✓ 替换后解析成功")
except Exception as e:
    print("✗ 替换后仍失败:", e)