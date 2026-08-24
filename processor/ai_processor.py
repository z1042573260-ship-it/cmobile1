"""
AI 处理器（向后兼容封装）
----------------------
已迁移到 processor.ai_pipeline（统一情报分析管线）。
本文件保留 DB 操作逻辑（RawProject → AI 分析 → Project 表），
但 AI 调用委托给 ai_pipeline.analyze_project()。

新代码请直接使用:
  from processor.ai_pipeline import run_unified_pipeline, analyze_project
"""
import json
import datetime
from loguru import logger

from config.settings import YANTAI_DISTRICTS, HIGH_PRIORITY_TYPES
from database.models import db, RawProject, Project
from database.db_manager import (
    get_unprocessed_raws, mark_as_processed, add_project,
)
from processor.ai_pipeline import analyze_project


def _map_unified_to_project(unified: dict, raw: RawProject) -> dict:
    """将统一 AI 结果映射回 Project 表字段（向后兼容）。"""
    return {
        "project_name": unified.get("project_name", raw.title),
        "project_type": unified.get("project_type", ""),
        "district": unified.get("district", ""),
        "location": unified.get("location", ""),
        "scale": unified.get("scale", ""),
        "investment": unified.get("investment", ""),
        "developer": unified.get("developer", ""),
        "contact_person": unified.get("contact_person", ""),
        "contact_phone": unified.get("contact_phone", ""),
        "publish_date": raw.publish_date or "",
        "deadline": unified.get("deadline", ""),
        "start_date": unified.get("start_date", ""),
        "end_date": unified.get("end_date", ""),
        "need_base_station": unified.get("need_base_station", "中"),
        "ai_reason": unified.get("ai_reason", ""),
        "priority": unified.get("priority", 3),
        "ai_summary": unified.get("ai_summary", ""),
        "source_name": raw.source_name,
        "source_url": raw.source_url or "",
        "raw_ids": str(raw.id),
    }


def process_single_project(raw: RawProject) -> bool:
    """
    处理单条原始项目（委托给统一 AI 管线分析，写入 Project 表）。

    返回 True 表示处理成功。
    """
    try:
        ai_result = analyze_project(
            title=raw.title,
            content=raw.content or "",
            publish_date=str(raw.publish_date or ""),
            source_url=raw.source_url or "",
            source_name=raw.source_name,
        )

        if not ai_result:
            logger.warning(f"AI 分析失败，跳过: {raw.title[:50]}")
            mark_as_processed(raw.id)
            return False

        data = _map_unified_to_project(ai_result, raw)

        add_project(
            project_name=data["project_name"],
            project_type=data["project_type"],
            district=data["district"],
            location=data["location"],
            scale=data["scale"],
            investment=data["investment"],
            developer=data["developer"],
            contact_person=data["contact_person"],
            contact_phone=data["contact_phone"],
            publish_date=data["publish_date"],
            deadline=data["deadline"],
            start_date=data["start_date"],
            end_date=data["end_date"],
            need_base_station=data["need_base_station"],
            ai_reason=data["ai_reason"],
            priority=data["priority"],
            ai_summary=data["ai_summary"],
            source_name=data["source_name"],
            source_url=data["source_url"],
            raw_ids=data["raw_ids"],
        )

        mark_as_processed(raw.id)

        logger.info(
            f"✅ AI分析完成: {data['project_name'][:40]} "
            f"| 基站需求:{data['need_base_station']} "
            f"| 优先级:{data['priority']}⭐"
        )
        return True

    except Exception as e:
        logger.error(f"处理项目异常 [{raw.id}]: {e}")
        mark_as_processed(raw.id)
        return False


def process_unprocessed(app, batch_size: int = 50) -> int:
    """
    批量处理所有未处理的原始项目。

    返回成功处理的数量。
    """
    processed = 0

    with app.app_context():
        unprocessed = get_unprocessed_raws(limit=batch_size)

        if not unprocessed:
            logger.info("无待处理的原始项目")
            return 0

        logger.info(f"开始 AI 处理 {len(unprocessed)} 条原始项目（委托给统一管线）...")

        for i, raw in enumerate(unprocessed):
            logger.info(f"  [{i+1}/{len(unprocessed)}] 分析中...")
            if process_single_project(raw):
                processed += 1

            if (i + 1) % 10 == 0:
                db.session.commit()
                logger.debug(f"  已提交批次 ({i+1}/{len(unprocessed)})")

        db.session.commit()

    return processed
