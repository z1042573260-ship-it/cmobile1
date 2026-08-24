import re
import json

with open('D:/googledownload/wangluobu_vscode/data/common_min.js', 'r', encoding='utf-8', errors='ignore') as f:
    js = f.read()

# 找API URL
patterns = [
    r'"(/jyxx/[^"]+)"',
    r"'(/jyxx/[^']+)'",
    r'"(/front/[^"]+)"',
    r"'(/front/[^']+)'",
    r'"([^"]*(?:query|search|getData|getList|loadData|queryList|findPage)[^"]*)"',
]

for pat in patterns:
    matches = list(set(re.findall(pat, js, re.IGNORECASE)))
    if matches:
        print(f'--- {pat[:50]}... ---')
        for m in matches[:10]:
            print(f'  {m[:150]}')
        print()

# 找pageSize/pageNum等
for m in re.findall(r'[a-zA-Z_]\w{2,30}', js):
    if 'page' in m.lower() or 'url' in m.lower() or 'api' in m.lower():
        pass  # too many, skip
print("\n=== 关键ajax函数 ===")
for m in re.findall(r'(function\s+\w*[Qq]uery\w*[^}]{0,200})', js):
    print(m[:200])
