"""
测试数据生成脚本
一次性运行即可，向数据库插入模拟项目数据用于看板效果预览。
"""
import sys
import datetime
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask
from config.settings import DATABASE_URL, FLASK_SECRET_KEY
from database.models import db, Project

# 模拟数据
PROJECTS = [
    # (名称, 类型, 区县, 规模, 基站需求, 优先级, 状态, 判断依据, 几周前)
    ("山海花园住宅小区二期", "住宅小区", "莱山区", "1200户/15万㎡", "高", 5, "新发现",
     "大型住宅小区1200户，入住后必然需要基站覆盖，优先级最高", 0),
    ("烟台市第一中学新校区", "学校", "芝罘区", "8万㎡/48班", "高", 5, "跟进中",
     "新建中学规模大，教学楼、宿舍区均需信号覆盖", 0),
    ("凤凰山隧道及接线工程", "隧道", "福山区", "全长2.3km", "高", 5, "新发现",
     "隧道是信号盲区，通车前必须完成基站部署", 1),
    ("烟台高新区科技创新园", "工业园区", "烟台高新区", "25万㎡/12栋", "高", 4, "跟进中",
     "大型科技园区，入驻企业多，通信需求密集", 1),
    ("滨海国际商业广场", "商业综合体", "芝罘区", "18万㎡/含写字楼+商场+酒店", "高", 5, "已签约",
     "商业综合体人流量大，多运营商必争之地", 2),
    ("牟平区妇幼保健院新院", "医院", "牟平区", "4.5万㎡/300床位", "高", 4, "跟进中",
     "医院建筑结构复杂，急症、病房、地下室均需全覆盖", 2),
    ("龙口市阳光花园住宅", "住宅小区", "龙口市", "680户/9万㎡", "高", 4, "新发现",
     "中型住宅小区，预计入住2000+人，基站刚需", 1),
    ("蓬莱阁景区升级改造", "景区", "蓬莱区", "改造面积3万㎡", "中", 3, "新发现",
     "景区人流量大，信号需求中等，需关注但非最高优先级", 3),
    ("莱阳农产品物流中心", "物流园区", "莱阳市", "10万㎡/含冷库+仓储", "高", 4, "跟进中",
     "物流园金属货架多信号干扰大，需专门基站部署方案", 3),
    ("招远市金城路市政改造", "市政设施", "招远市", "道路6.2km/管线8km", "低", 2, "新发现",
     "市政道路改造不含地下工程，基站需求低", 4),
    ("海阳恒大悦澜湾住宅", "住宅小区", "海阳市", "900户/12万㎡", "高", 4, "新发现",
     "中大型住宅，恒大品牌开发商，入住率高", 2),
    ("栖霞市体育运动中心", "体育场馆", "栖霞市", "3万㎡/8000座", "中", 3, "已签约",
     "体育场馆平时信号需求一般，赛事期间需应急通信车", 4),
    ("烟台开发区人才公寓", "住宅小区", "烟台开发区", "420户/6万㎡", "中", 3, "新发现",
     "中小型住宅，优先关注大型住宅项目", 5),
    ("莱州湾跨海大桥接线", "桥梁", "莱州市", "主线1.8km/匝道3km", "中", 3, "已丢失",
     "桥梁非隧道，信号覆盖难度不高，竞对已签约", 5),
    ("烟台保税港区仓储中心", "物流园区", "烟台保税港区", "5万㎡仓储+办公", "高", 4, "新发现",
     "保税区特殊建筑结构，需宏站+室分组合方案", 3),
    ("芝罘区万达广场改造", "商业综合体", "芝罘区", "改造2万㎡", "低", 2, "已丢失",
     "仅室内改造非新建，基站需求低，竞对已介入", 6),
    ("山东省中医药学校新校区", "学校", "莱山区", "12万㎡/60班", "高", 5, "已签约",
     "大型学校，教学楼+宿舍+实验室全需覆盖，已成功签约", 6),
    ("福山区人民医院扩建", "医院", "福山区", "扩建3万㎡/200床位", "高", 4, "跟进中",
     "医院扩建新增住院楼，需要新增室分系统", 5),
    ("长岛海洋生态旅游度假村", "景区", "长岛综合试验区", "5万㎡/含酒店+商业街", "中", 3, "新发现",
     "海岛景区，现有基站覆盖弱，但项目规模中等", 4),
    ("烟台智慧城市数据中心", "其他", "烟台高新区", "2万㎡/5000机柜", "高", 4, "新发现",
     "数据中心非人员密集但周边配套办公区需要覆盖", 7),
]

app = Flask(__name__)
app.config["SECRET_KEY"] = FLASK_SECRET_KEY
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

from database.models import db
db.init_app(app)

with app.app_context():
    db.create_all()

    # 避免重复插入
    if Project.query.count() > 0:
        print(f"数据库已有 {Project.query.count()} 条数据，跳过。如需重新生成请先删除 intelligence.db")
        sys.exit(0)

    today = datetime.date.today()
    count = 0
    for (name, ptype, district, scale, need, priority, status, reason, weeks_ago) in PROJECTS:
        created_date = today - datetime.timedelta(weeks=weeks_ago, days=random.randint(0, 6))

        p = Project(
            project_name=name,
            project_type=ptype,
            district=district,
            location=f"烟台市{district}",
            scale=scale,
            investment=f"{random.randint(800, 50000)}万元",
            developer=["烟台城建集团", "中建八局", "万科地产", "龙湖集团", "碧桂园",
                       "绿城中国", "保利发展", "华润置地", "烟台港集团", "山东高速"][count % 10],
            contact_person=["张经理", "李工", "王总", "赵工", "陈经理"][count % 5],
            contact_phone=f"138{random.randint(10000000,99999999)}",
            publish_date=(created_date - datetime.timedelta(days=random.randint(0, 5))).isoformat(),
            deadline=(created_date + datetime.timedelta(days=random.randint(10, 60))).isoformat(),
            need_base_station=need,
            ai_reason=reason,
            priority=priority,
            ai_summary=f"[{district}][{ptype}] {name}，规模{scale}。" + reason[:30],
            source_name=["烟台市公共资源交易网", "中国土地市场网", "山东省投资项目审批平台",
                        "烟台市自然资源和规划局", "乙方宝"][count % 5],
            source_url="https://example.com/project/" + str(count),
            status=status,
            notified=(status == "已签约"),
            notified_at=(datetime.datetime.now() - datetime.timedelta(days=random.randint(1, 7)))
                        if status == "已签约" else None,
            created_at=datetime.datetime.combine(created_date, datetime.time(
                random.randint(8, 20), random.randint(0, 59))),
            updated_at=datetime.datetime.now(),
        )
        db.session.add(p)
        count += 1

    db.session.commit()
    print(f"[OK] 成功插入 {count} 条测试数据！")
    print("现在重启看板就能看到效果了")
