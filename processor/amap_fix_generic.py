# -*- coding: utf-8 -*-
"""对『location 笼统(=区县名/待核实)』而被压在区县中心的红/黄记录，改用『区县+项目名称』检索解压。"""
import json, sys, os, time, re
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from amap_geocode import geocode, region_ok, SLEEP

OFFICE = ["海阳市行政审批服务局关于", "海阳市自然资源和规划局关于",
          "烟台市行政审批服务局关于", "烟台市自然资源和规划局关于",
          "海阳市行政审批服务局", "海阳市自然资源和规划局",
          "关于", "《建设用地规划许可证》核发批后公布", "《建设工程规划许可证》",
          "核发批后公布", "核发批前公示", "批前公示", "批后公告", "调整规划",
          "规划设计方案公示", "建筑立面调整方案批前公示", "公开公示",
          "社会稳定风险评估信息公示", "选址意见书", "《建设用地规划许可证》"]

def clean_name(name):
    s = name or ""
    for p in OFFICE:
        s = s.replace(p, "")
    s = re.sub(r"《.*?》", "", s)
    s = s.replace("海阳市", "").replace("烟台市", "").replace("烟台高新区", "").replace("高新区", "")
    return s.strip(" ，、（）()")

def is_generic(loc, dist):
    if not loc: return True
    s = loc.strip()
    if s in (dist, dist+"市", dist+"区", dist+"县", "待核实", "城区",
             "海阳市城区", "具体位置待核实", "烟台市", "烟台高新区", "高新区", "开发区"):
        return True
    return False

def run(json_path):
    d = json.load(open(json_path, encoding="utf-8"))
    flag = [r for r in d if r.get("warning_level") in ("红色预警","黄色预警")
            and "lng" in r and is_generic(r.get("location",""), r.get("district",""))]
    rescued = 0
    for r in flag:
        dist = r.get("district","")
        name = clean_name(r.get("project_name",""))
        if not name:
            continue
        g = geocode(name, "烟台市")
        if g and region_ok(dist, g):
            new = {}
            for kk, vv in r.items():
                new[kk] = vv
                if kk == "location":
                    new["lng"] = g["lng"]; new["lat"] = g["lat"]
            if "location" not in new:
                new["lng"] = g["lng"]; new["lat"] = g["lat"]
            new["geo_source"] = "项目名检索(高德)"
            r.clear(); r.update(new)
            rescued += 1
            time.sleep(SLEEP)
    json.dump(d, open(json_path,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"项目名检索解压：救回 {rescued} / {len(flag)} 条笼统记录")

if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv)>1 else r"D:/googledownload/wangluobu_vscode/data/results/workbuddy.json"
    run(p)
