import json
import re
from pathlib import Path

p = Path(__file__).parent / 'sobija.json'
out = Path(__file__).parent / 'sobija.json2'
print('Reading', p)
text = p.read_text(encoding='utf-8')
try:
    data = json.loads(text)
except Exception as e:
    print('JSON load error:', e)
    raise

processed = []
current = None
for item in data.get('Sheet1', []) if isinstance(data, dict) else []:
    if item is None:
        continue
    if isinstance(item, dict):
        for k, v in item.items():
            if not isinstance(v, str):
                continue
            if v.strip() == '' or v.strip().lower() == 'null':
                continue
            m = re.search(r'제(\d+)조', v)
            if m:
                current = f"제{m.group(1)}조"
                processed.append({k: v})
            else:
                if current:
                    processed.append({k: f"{current} {v}"})
                else:
                    processed.append({k: v})
    else:
        continue

if isinstance(data, dict):
    data['Sheet1'] = processed

out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print('Wrote', out)
