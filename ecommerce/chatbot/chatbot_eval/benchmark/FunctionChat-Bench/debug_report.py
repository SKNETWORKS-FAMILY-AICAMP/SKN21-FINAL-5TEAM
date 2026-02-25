
import json

file_path = "output/my-ecommerce-bot/FunctionChat-Singlecall.my-ecommerce-bot.eval_report.tsv"

try:
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
        
    headers = lines[0].strip().split('\t')
    print(f"Headers: {headers}")

    for i, line in enumerate(lines[1:]):
        parts = line.strip().split('\t')
        if len(parts) >= 7:
            sn = parts[0]
            is_pass = parts[1]
            gt = parts[3]
            mo = parts[5]
            reason = parts[6]
            
            print(f"\n--- Row {i+1} (Serial {sn}) ---")
            print(f"Pass: {is_pass}")
            print(f"GT: {gt[:200]}...") # Truncate for readability
            print(f"MO: {mo[:200]}...")
            print(f"Reason: {reason}")
            
except Exception as e:
    print(f"Error: {e}")
