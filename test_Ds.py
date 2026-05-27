import requests

api_key = "sk-53aea0acc2404635be9d5e753e498eba"
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

# 1. 密钥连通校验
try:
    resp = requests.get("https://api.deepseek.com/v1/models", headers=headers, timeout=10)
    print("状态码:", resp.status_code)
    if resp.status_code == 200:
        print("✅ API连通正常，可用模型：", [m["id"] for m in resp.json()["data"]])
except Exception as e:
    print("❌ 连接异常:", e)

# 2. 对话实测
data = {
    "model": "deepseek-chat",
    "messages": [{"role":"user","content":"测试调用"}]
}
resp = requests.post("https://api.deepseek.com/v1/chat/completions", headers=headers, json=data, timeout=10)
print("对话响应:", resp.json() if resp.status_code==200 else resp.text)