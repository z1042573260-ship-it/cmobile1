"""
全局配置文件
-----------
所有可配置项集中在这里，方便修改。
豆包 API Key、邮箱密码等敏感信息建议通过环境变量或 .env 文件设置。
"""
import os
from pathlib import Path

# ===== 项目根目录 =====
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"

# 确保目录存在
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# 敏感配置统一从 .env 加载（.env 不入库，线上由 GitHub Secrets 注入环境变量）
# .env 示例见 .env.example
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

# ===== 数据库 =====
# DB_MODE: local=本地 MySQL / tidb=TiDB Cloud（默认 tidb，线上部署用）
# 格式: mysql+pymysql://用户名:密码@主机:端口/数据库名
# 注意：TIDB_DATABASE_URL 含密码，必须放 .env / 环境变量（线上 GitHub Actions 用 Secrets 注入），
#       不要写死在代码里（仓库公开后会被泄露）。ssl_ca 用相对路径 config/tidb_ca.pem（CA 证书非机密，可入库）。
DB_MODE = os.getenv("DB_MODE", "tidb")
LOCAL_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:1234@localhost:3306/yantai_projects",
)
TIDB_DATABASE_URL = os.getenv("TIDB_DATABASE_URL", "")
DATABASE_URL = TIDB_DATABASE_URL if DB_MODE == "tidb" else LOCAL_DATABASE_URL

# ===== 豆包 API（火山引擎）— 已弃用（key 曾泄露，勿再填入明文 key）=====
# DOUBAO_API_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
# DOUBAO_MODEL = "ep-20260724111223-jx58k"

# ===== 智谱 AI（GLM）=====
# API Key 敏感，走 .env / 环境变量（本地 .env，线上 GitHub Secrets）
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")
ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
ZHIPU_MODEL = "glm-4-flash"  # 免费且实测质量最稳（4.7 余额不足；4.5-air 长 prompt 模板化；4.7-flash 思考草稿）

# ===== 讯飞星火（免费 + 联网搜索，坐标补全用）=====
XFYUN_API_KEY = os.getenv("XFYUN_API_KEY", "")     # xinghuo.xfyun.cn，走 .env
XFYUN_API_SECRET = os.getenv("XFYUN_API_SECRET", "")
XFYUN_BASE_URL = "https://spark-api-open.xf-yun.com/v1"
XFYUN_MODEL = "lite"                              # Spark Lite 永久免费

# ===== 邮件配置（QQ邮箱）=====
EMAIL_SMTP_SERVER = "smtp.qq.com"
EMAIL_SMTP_PORT = 465  # SSL
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "1042573260@qq.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")  # QQ邮箱授权码，走 .env（敏感）
EMAIL_RECIPIENTS = os.getenv(
    "EMAIL_RECIPIENTS",
    "1042573260@qq.com,wuqingyuan@sd.chinamobile.com",
).split(",")  # 逗号分隔的收件人列表

# ===== 爬虫配置 =====
# 烟台各区县列表
YANTAI_DISTRICTS = [
    "芝罘区", "莱山区", "福山区", "牟平区",
    "蓬莱区", "龙口市", "莱阳市", "莱州市",
    "招远市", "栖霞市", "海阳市", "长岛综合试验区",
    "烟台开发区", "烟台高新区", "烟台保税港区",
]

# 爬虫请求间隔（秒），避免被封IP
CRAWL_INTERVAL = 10

# 爬虫 User-Agent
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ===== AI 分析配置 =====
# 高优先级工程类型（这些类型建完后必然需要基站）
HIGH_PRIORITY_TYPES = [
    "住宅小区", "商业综合体", "写字楼", "办公楼",
    "学校", "医院", "体育场馆", "会展中心",
    "工业园区", "科技园区", "物流园区",
    "隧道", "地下空间", "地下管廊",
    "交通枢纽", "地铁站", "火车站", "机场",
    "酒店", "商场", "大型超市",
    "景区", "度假村", "游乐场",
]

# B2B 商机分析输出路径（旧，保留兼容）
BUSINESS_OUTPUT_JSON = str(DATA_DIR / "dashboard_data.json")
BUSINESS_DB_PATH = str(DATA_DIR / "b2b_warnings.db")

# 统一情报分析输出路径（新）
UNIFIED_OUTPUT_JSON = str(DATA_DIR / "unified_intelligence.json")
UNIFIED_DB_PATH = str(DATA_DIR / "unified_intelligence.db")

# 联网搜索 API 配置（预留，当前不需要——爬虫数据来自政府官网）
WEB_SEARCH_API_URL = os.getenv("WEB_SEARCH_API_URL", "")
WEB_SEARCH_API_KEY = os.getenv("WEB_SEARCH_API_KEY", "")

# ===== Flask 配置 =====
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "change-me-to-a-random-string-in-production")
FLASK_HOST = "0.0.0.0"  # 允许局域网内其他电脑访问
FLASK_PORT = 5000

# ===== 日志 =====
LOG_LEVEL = "INFO"
LOG_FILE = LOG_DIR / "app.log"
LOG_ROTATION = "10 MB"
LOG_RETENTION = "30 days"
