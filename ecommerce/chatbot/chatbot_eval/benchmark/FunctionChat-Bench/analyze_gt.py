import json
import sys

# Set stdout to utf-8 for Windows
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open('data/my_eval_dataset_100_updated.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        serial = data.get('function_num', '??')
        user_msg = data.get('query', [{}])[0].get('content', '')
        
        if not data.get('ground_truth'): 
            print(f"[{serial}] {user_msg} -> NO TOOL")
            continue
        gt = json.loads(data['ground_truth'][0]['content'])
        name = gt.get('name', '??')
        args = gt.get('arguments', {})
        print(f"[{serial}] {user_msg} -> {name}({args})")

