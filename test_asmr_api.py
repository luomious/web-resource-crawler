import requests, json, pathlib

url = 'https://www.asmr.one/work/RJ01568719'

# Check what APIs work
apis = [
    'https://www.asmr.one/api/work/RJ01568719',
    'https://asmr.one/api/tracks/RJ01568719',
    'https://www.asmr.one/api/workInfo/RJ01568719',
    'https://api.asmr.one/tracks/RJ01568719',
]

out = pathlib.Path(r"E:\test_asmr_result.txt")
lines = []

for api in apis[:3]:
    try:
        r = requests.get(api, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        lines.append(f'\n=== {api} -> {r.status_code} ===')
        try:
            data = r.json()
            lines.append(json.dumps(data, indent=2, ensure_ascii=False)[:2000])
        except:
            lines.append(r.text[:1000])
    except Exception as e:
        lines.append(f'{api} -> {str(e)}')

out.write_text('\n'.join(lines), encoding='utf-8')
print("Done - check E:/test_asmr_result.txt")
