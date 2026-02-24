import json
import os

filepath = r'c:\Users\Playdata\Documents\FunctionChat-Bench\FunctionChat-Bench\data\my_eval_dataset_expanded.jsonl'
with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()
    for i in range(0, len(lines), 5):
        for j in range(i, min(i+5, len(lines))):
            row = json.loads(lines[j])
            gt_names = []
            for gt in row.get('ground_truth', []):
                if gt.get('content'):
                    try:
                        gt_names.append(json.loads(gt['content'])['name'])
                    except:
                        gt_names.append("INVALID_JSON")
            print(f"{j+1:2}: {row['function_name']} -> {gt_names}")
        print("---")
