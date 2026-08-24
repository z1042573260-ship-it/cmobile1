# -*- coding: utf-8 -*-
"""修复 workbuddy2.json 的 location 字段（管线口径）。
管线规范（ai_pipeline.py）：L163-168 位置须来自原文/搜索，禁止模板文字；L901 找不到填"待核实"。
本脚本：重新从 content 提取真实地址 → 提取不到置"待核实"（不填空/不填模板文字）。lng/lat 不动。"""

import json
import re

P = 'data/results/workbuddy2.json'

# 表头/模板噪声词：地址标签后若紧跟这些词，说明"地址"是表头列名而非真实标签
HEADER_WORDS = [
    '有效期限', '审批时间', '备注', '证号', '序号', '企业名称', '项目名称',
    '许可证号', '用地性质', '建设规模', '公示时间', '公示期', '核发日期',
    '有效期至', '意见受理', '监督单位', '联系', '邮编', '附图', '年度',
    '用地单位', '项目编号', '招标方式', '合同预估', '信息来源', '发布日期',
]

def extract_addr_v2(content, district=''):
    """管线口径地址提取：真实地址 → 否则返回 None（由调用方置'待核实'）。"""
    if not content:
        return None
    c = str(content)
    # 去掉常见公示模板头部（法规引用、欢迎语）
    c = re.sub(r'(为提高城市规划的透明度[^。]{0,80}。|根据《中华人民共和国城乡规划法[^。]{0,120}。|欢迎广大市民(提出宝贵意见|参与[^。]{0,60}。))', '', c)

    # 1) 显式标签（标签后非表头词才算）
    for label in ['建设地点', '项目位置', '拟建位置', '拟选址', '用地位置', '具体位置', '选址', '坐落', '座落', '位于']:
        for m in re.finditer(label + r'\s*[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9号路街巷乡村镇区栋层室园侧东西南北中，、\-0-9]{3,60})', c):
            a = m.group(1).strip('，、。 ；;')
            if len(a) >= 3 and not any(h in a[:12] for h in HEADER_WORDS):
                return a

    # 2) 表格型公告："地址"是列名，其后紧跟表头词则跳过列名，尝试抓列值
    #    模式：地址 <值> 有效期限（值多为"XX路XX侧"式短地址）
    m = re.search(r'地址\s+([\u4e00-\u9fa5A-Za-z0-9号路街巷乡村镇区栋层室园侧东西南北中，、\-]{3,40}?)\s+(?:有效期限|审批时间|备注|证号|序号)', c)
    if m:
        a = m.group(1).strip('，、。 ')
        if len(a) >= 3 and not any(h in a[:12] for h in HEADER_WORDS):
            return a

    # 3) 锚定"位于 XX"（限制为路/街/村/园等特征，且不跨标点）
    m = re.search(r'(?:位于|坐落于)[^\u4e00-\u9fa5]*([\u4e00-\u9fa5]{2,18}(?:路|街|大道|镇|乡|村|园区|工业区|街道|巷|路与|街与|大道与)[^\s，。；]{0,16})', c)
    if m:
        a = m.group(1).strip()
        if not any(h in a for h in HEADER_WORDS):
            return a

    return None

def main():
    d = json.load(open(P, encoding='utf-8'))
    fixed = {'ok_addr': 0, 'to_pending': 0, 'kept': 0}
    poll_mark = ['有效期限', '城乡规划', '年度', '用地性质', '项目合作方式', '许可证号',
                 '审批时间', '备注', '施工许可证', '公示表', '项目编号', '牵头单位',
                 '合作方式', '规划法', '条例', '招标公告']
    for x in d:
        old = (x.get('location') or '').strip()
        addr = extract_addr_v2(x.get('content') or '', x.get('district') or '')
        if addr:
            x['location'] = addr
            fixed['ok_addr'] += 1
        else:
            # 管线口径：找不到 → 待核实（若原来就是干净地址则保留，但污染/空/区县名统一处理）
            if old and len(old) <= 20 and not any(k in old for k in poll_mark) and old not in ('待核实',):
                x['location'] = old  # 原来就是短地址（如"海阳市西安路以东"），保留
                fixed['kept'] += 1
            else:
                x['location'] = '待核实'
                fixed['to_pending'] += 1

    json.dump(d, open(P, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    # 校验
    bad = [x.get('location') for x in d if any(k in (x.get('location') or '') for k in poll_mark)]
    empty = sum(1 for x in d if not (x.get('location') or '').strip())
    pending = sum(1 for x in d if x.get('location') == '待核实')
    print('修复统计:', fixed)
    print('剩余模板污染:', len(bad))
    print('空值:', empty, '| 待核实:', pending)
    # 展示样例
    print()
    print('=== 修复后 location 样例（前 20 条非待核实） ===')
    cnt = 0
    for x in d:
        if x.get('location') and x['location'] != '待核实' and cnt < 20:
            print('  [%02d] %-26s -> %s' % (x['_index'], x['project_name'][:26], x['location']))
            cnt += 1

if __name__ == '__main__':
    main()
