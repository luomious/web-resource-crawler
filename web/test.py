import json, urllib.request, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Test
req = urllib.request.Request("http://localhost:18777/")
resp = urllib.request.urlopen(req, timeout=5)
assert resp.status == 200, f"Status: {resp.status}"
print("OK: Index 200")

data = json.dumps({"urls": ["https://www.asmr.one/work/RJ01568719"]}).encode()
req = urllib.request.Request("http://localhost:18777/fetch", data=data,
                              headers={"Content-Type": "application/json"})
resp = urllib.request.urlopen(req, timeout=30)
result = json.loads(resp.read())
r = result["resources"]
audio = sum(1 for x in r if x["rtype"] == "音频")
sub = sum(1 for x in r if x["rtype"] == "字幕")
valid = sum(1 for x in r if x.get("url", "").startswith("http"))
assert len(r) == 113, f"Count error: {len(r)}"
assert valid == 113, f"URL error: {valid}"
print(f"OK: {len(r)} resources ({audio} audio + {sub} subtitle)")
