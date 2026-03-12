import json, sys

eval_file = 'output/arg_acc/gpt-4o-mini/FunctionChat-Dialog.gpt-4o-mini.eval.jsonl'
input_file = 'output/arg_acc/gpt-4o-mini/FunctionChat-Dialog.input.jsonl'

lines = [json.loads(l) for l in open(eval_file, encoding='utf-8-sig') if l.strip()]
inputs = [json.loads(l) for l in open(input_file, encoding='utf-8-sig') if l.strip()]
input_map = {i['serial_num']: i for i in inputs}

with open('fail_result.txt', 'w', encoding='utf-8') as out:
    passed = []
    failed = []
    for l in lines:
        ra = l.get('report_arguments', {})
        is_pass = ra.get('is_pass')
        if is_pass == 'pass':
            passed.append(l)
        else:
            failed.append(l)

    out.write(f"Total: {len(lines)}, Pass: {len(passed)}, Failed: {len(failed)}\n")
    out.write(f"Pass rate: {len(passed)/len(lines)*100:.1f}%\n\n")

    out.write("=== PASS ===\n")
    for p in passed:
        ra = p.get('report_arguments', {})
        sn = ra.get('serial_num', '?')
        inp = input_map.get(sn, {})
        out.write(f"  [#{sn}] {inp.get('scenario_name','?')}\n")
    out.write("\n")

    out.write("=== FAIL ===\n")
    for f in failed:
        ra = f.get('report_arguments', {})
        sn = ra.get('serial_num', '?')
        inp = input_map.get(sn, {})
        sname = inp.get('scenario_name', '?')
        
        er = f.get('evaluate_response', {})
        reason_text = ""
        if er and 'choices' in er:
            reason_text = er['choices'][0]['message']['content'].strip()
        
        mr = f.get('model_response', {})
        model_tool_calls = mr.get('tool_calls', [])
        model_content = mr.get('content', '')
        
        gt = inp.get('ground_truth', {})
        gt_tc = gt.get('tool_calls', [])
        gt_func = gt_tc[0].get('function', {}).get('name', '') if gt_tc else 'N/A'
        gt_args = gt_tc[0].get('function', {}).get('arguments', {}) if gt_tc else {}
        
        msgs = inp.get('messages', [])
        has_system = any(m.get('role') == 'system' for m in msgs)
        user_msg = next((m['content'] for m in msgs if m['role'] == 'user'), '')
        
        out.write(f"[#{sn}] {sname}\n")
        out.write(f"  시스템프롬프트: {'O' if has_system else 'X'}\n")
        out.write(f"  질문: {user_msg[:100]}\n")
        out.write(f"  기대: {gt_func} -> {json.dumps(gt_args, ensure_ascii=False)}\n")
        
        if model_tool_calls:
            for tc in model_tool_calls:
                fn = tc.get('function', {})
                out.write(f"  실제: {fn.get('name','?')} -> {fn.get('arguments','?')[:120]}\n")
        elif model_content:
            out.write(f"  실제: [텍스트응답] {model_content[:120]}\n")
        else:
            out.write(f"  실제: [응답없음]\n")
        
        reason_first = reason_text.split('\n')[1] if len(reason_text.split('\n')) > 1 else reason_text
        out.write(f"  원인: {reason_first}\n\n")

print("Done! See fail_result.txt")
