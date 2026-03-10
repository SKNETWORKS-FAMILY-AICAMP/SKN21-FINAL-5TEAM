from pathlib import Path
text = Path('ecommerce/chatbot/src/graph/nodes_v2.py').read_text()
if 'class TaskType' in text:
    idx = text.index('class TaskType')
    print(text[idx:idx+800])
else:
    print('not found')
