"""订阅源抓取：下载 M3U -> 解析 -> 按 (source_id, url) upsert 入库。"""
import logging
from datetime import datetime

import httpx

from .db import SessionLocal
from .models import Source, Channel
from .m3u import parse_m3u, normalize_name

log = logging.getLogger("iptv.fetcher")
TIMEOUT = 30


def _http_client() -> httpx.Client:
    kwargs = dict(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (iptv-manager)"},
    )
    try:
        return httpx.Client(**kwargs)  # 优先走系统代理设置
    except Exception as e:  # noqa: BLE001 - 代理环境变量损坏时直连
        log.warning("proxy env unusable (%s), connecting directly", e)
        return httpx.Client(**kwargs, trust_env=False)


def fetch_source(source_id: int) -> dict:
    """抓取单个源，返回 {"added": n, "updated": n, "total": n} 或 {"error": msg}。"""
    db = SessionLocal()
    try:
        src = db.get(Source, source_id)
        if not src:
            return {"error": "source not found"}
        try:
            with _http_client() as client:
                r = client.get(src.url)
                r.raise_for_status()
                text = r.text
        except Exception as e:  # noqa: BLE001 - 抓取失败只记录
            src.last_status = "error"
            src.last_message = f"{type(e).__name__}: {e}"[:500]
            src.last_fetch = datetime.utcnow()
            db.commit()
            log.warning("fetch source %s failed: %s", src.name, e)
            return {"error": src.last_message}

        parsed = parse_m3u(text)
        added, updated = 0, 0
        for p in parsed:
            if not p.url:
                continue
            ch = (
                db.query(Channel)
                .filter(Channel.source_id == src.id, Channel.url == p.url)
                .first()
            )
            norm = normalize_name(p.name)
            if ch:
                # 同 URL 已存在：刷新源站信息，但不覆盖用户改过的 name/category
                ch.orig_name = p.name
                ch.norm_name = norm
                ch.logo = p.logo or ch.logo
                ch.tvg_id = p.tvg_id or ch.tvg_id
                if not ch.category and p.group:
                    ch.category = p.group
                ch.source_name = src.name
                ch.updated_at = datetime.utcnow()
                updated += 1
            else:
                ch = Channel(
                    name=p.name,
                    norm_name=norm,
                    orig_name=p.name,
                    url=p.url,
                    logo=p.logo,
                    tvg_id=p.tvg_id,
                    category=p.group or "未分类",
                    source_id=src.id,
                    source_name=src.name,
                    enabled=True,
                )
                db.add(ch)
                added += 1
        src.last_fetch = datetime.utcnow()
        src.last_status = "ok"
        src.last_message = f"added {added}, updated {updated}"
        src.channel_count = db.query(Channel).filter(Channel.source_id == src.id).count()
        db.commit()
        log.info("fetch source %s: added=%d updated=%d", src.name, added, updated)
        return {"added": added, "updated": updated, "total": len(parsed)}
    finally:
        db.close()


def fetch_all_enabled() -> list[dict]:
    db = SessionLocal()
    try:
        ids = [s.id for s in db.query(Source).filter(Source.enabled == True).all()]  # noqa: E712
    finally:
        db.close()
    return [{"source_id": i, **fetch_source(i)} for i in ids]
