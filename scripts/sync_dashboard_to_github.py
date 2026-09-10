# -*- coding: utf-8 -*-
"""
把大屏数据文件同步到 GitHub 仓库（用 GitHub Contents API，不走 git push）

为什么不用 git push：GitHub 与 Gitee 两个仓库历史分叉（内容相同、commit hash 不同），
从 Gitee 容器 push 到 GitHub 必然 `! [rejected] (fetch first)`。API 方式直接按文件内容
创建提交（自动基于远端当前 HEAD），不涉及本地历史，永不冲突。

用法（CI 或本地）：
    GITHUB_PUSH_TOKEN=ghp_xxx python scripts/sync_dashboard_to_github.py
    python scripts/sync_dashboard_to_github.py --repo OWNER/REPO --files a.json b.json

环境变量：
    GITHUB_PUSH_TOKEN  GitHub PAT（勾 repo 权限）
    GITHUB_REPO        可选，默认 z1042573260-ship-it/cmobile1
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests

DEFAULT_REPO = "z1042573260-ship-it/cmobile1"
DEFAULT_FILES = [
    "frontend/data/dashboard_data.json",
    "frontend/data/report_data.json",
    "frontend/data/workbuddy.json",
    "data/unified_intelligence.checkpoint.json",   # AI 断点（中断续跑用，避免重复花钱）
]
API = "https://api.github.com"


def local_blob_sha(path):
    """本地文件的 git blob SHA（与 git hash-object 一致，与文件大小无关）"""
    with open(path, "rb") as f:
        data = f.read()
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def get_remote_meta(session, repo, path, branch):
    """远端文件元信息（不存在返回 None）。GET /contents 返回的 sha 即 blob sha，
    对任意大小文件都可靠（大文件不返回 content，故不能用文本比对判等）"""
    r = session.get(f"{API}/repos/{repo}/contents/{path}",
                    params={"ref": branch}, timeout=30)
    if r.status_code == 200:
        return r.json()
    if r.status_code == 404:
        return None
    raise RuntimeError(f"读取 {path} 失败: HTTP {r.status_code} {r.text[:120]}")


def sync_file(session, repo, path, branch, message):
    """同步单个文件；返回 (状态, 说明)"""
    if not os.path.exists(path):
        return "skip", "本地文件不存在"
    with open(path, "rb") as f:
        raw = f.read()

    meta = get_remote_meta(session, repo, path, branch)
    if meta and meta.get("sha") == local_blob_sha(path):
        return "same", "远端内容一致，跳过"

    payload = {
        "message": message,
        "content": base64.b64encode(raw).decode(),
        "branch": branch,
    }
    if meta and meta.get("sha"):
        payload["sha"] = meta["sha"]
    r = session.put(f"{API}/repos/{repo}/contents/{path}", json=payload, timeout=60)
    if r.status_code in (200, 201):
        commit = (r.json().get("commit") or {}).get("sha", "")[:8]
        return "ok", f"已提交 {commit}"
    return "fail", f"HTTP {r.status_code} {r.text[:160]}"


def main():
    ap = argparse.ArgumentParser(description="大屏数据 → GitHub（API 方式，不依赖 git 历史）")
    ap.add_argument("--repo", default=os.getenv("GITHUB_REPO", DEFAULT_REPO))
    ap.add_argument("--branch", default="main")
    ap.add_argument("--files", nargs="+", default=DEFAULT_FILES)
    ap.add_argument("--token", default=os.getenv("GITHUB_PUSH_TOKEN", ""))
    ap.add_argument("--message", default=None)
    args = ap.parse_args()

    if not args.token:
        print("SKIP: 未提供 GITHUB_PUSH_TOKEN（数据已在 TiDB，跳过 GitHub 同步）")
        return 0

    msg = args.message or f"chore(data): 自动更新大屏数据 {time.strftime('%Y-%m-%d %H:%M')}"
    session = requests.Session()
    session.trust_env = False
    session.headers.update({
        "Authorization": f"token {args.token}",
        "Accept": "application/vnd.github+json",
    })

    results = []
    for path in args.files:
        try:
            status, note = sync_file(session, args.repo, path, args.branch, msg)
        except Exception as e:
            status, note = "fail", str(e)[:160]
        mark = {"ok": "OK  ", "same": "SAME", "skip": "SKIP", "fail": "FAIL"}[status]
        print(f"[{mark}] {path} — {note}")
        results.append(status)

    if "fail" in results:
        print("部分文件同步失败（数据已在 TiDB，不影响其他步骤）")
        return 0   # 不让 CI 因同步失败而中断
    print(f"同步完成：{results.count('ok')} 个文件已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
