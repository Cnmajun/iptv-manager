"""IPTV 订阅管理服务：多源聚合 / 定时更新 / 改名删台归类 / 同名合并 / 定制输出。"""
import json
import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from .models import Source, Channel, Playlist
from . import scheduler as sched
from .fetcher import fetch_source
from .m3u import build_m3u, normalize_name

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("iptv")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    # 轻量迁移：老库补 backup_urls 列
    with engine.begin() as conn:
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(channels)").fetchall()]
        if "backup_urls" not in cols:
            conn.exec_driver_sql("ALTER TABLE channels ADD COLUMN backup_urls TEXT DEFAULT '[]'")
    sched.start()
    yield
    sched.shutdown()


app = FastAPI(title="IPTV Manager", version="0.1.0", lifespan=lifespan)


# ---------- 订阅源 ----------
class SourceIn(BaseModel):
    name: str
    url: str
    enabled: bool = True
    interval_hours: int = 12


@app.get("/api/sources")
def list_sources(db: Session = Depends(get_db)):
    return [
        {
            "id": s.id, "name": s.name, "url": s.url, "enabled": s.enabled,
            "interval_hours": s.interval_hours,
            "last_fetch": s.last_fetch.isoformat() if s.last_fetch else None,
            "last_status": s.last_status, "last_message": s.last_message,
            "channel_count": s.channel_count,
        }
        for s in db.query(Source).order_by(Source.id).all()
    ]


@app.post("/api/sources")
def create_source(body: SourceIn, db: Session = Depends(get_db)):
    s = Source(name=body.name.strip(), url=body.url.strip(),
               enabled=body.enabled, interval_hours=max(1, body.interval_hours))
    db.add(s)
    db.commit()
    db.refresh(s)
    sched.schedule_source(s)
    return {"id": s.id}


@app.put("/api/sources/{sid}")
def update_source(sid: int, body: SourceIn, db: Session = Depends(get_db)):
    s = db.get(Source, sid)
    if not s:
        raise HTTPException(404, "source not found")
    s.name, s.url = body.name.strip(), body.url.strip()
    s.enabled, s.interval_hours = body.enabled, max(1, body.interval_hours)
    db.commit()
    sched.schedule_source(s)
    return {"ok": True}


@app.delete("/api/sources/{sid}")
def delete_source(sid: int, db: Session = Depends(get_db)):
    s = db.get(Source, sid)
    if not s:
        raise HTTPException(404, "source not found")
    sched.remove_source(sid)
    db.query(Channel).filter(Channel.source_id == sid).delete()
    db.delete(s)
    db.commit()
    return {"ok": True}


@app.post("/api/sources/{sid}/refresh")
def refresh_source(sid: int):
    return fetch_source(sid)


# ---------- 频道 ----------
class ChannelPatch(BaseModel):
    name: str | None = None
    category: str | None = None
    enabled: bool | None = None


def _channel_dict(c: Channel) -> dict:
    try:
        backups = json.loads(c.backup_urls or "[]")
    except Exception:
        backups = []
    return {
        "id": c.id, "name": c.name, "norm_name": c.norm_name, "orig_name": c.orig_name,
        "url": c.url, "logo": c.logo, "category": c.category,
        "source_id": c.source_id, "source_name": c.source_name,
        "enabled": c.enabled, "backup_urls": backups,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


@app.get("/api/channels")
def list_channels(
    search: str = "", category: str = "", source_id: int = 0,
    enabled: str = "", page: int = 1, per_page: int = Query(50, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(Channel)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(Channel.name.like(like), Channel.orig_name.like(like)))
    if category:
        q = q.filter(Channel.category == category)
    if source_id:
        q = q.filter(Channel.source_id == source_id)
    if enabled == "1":
        q = q.filter(Channel.enabled == True)  # noqa: E712
    elif enabled == "0":
        q = q.filter(Channel.enabled == False)  # noqa: E712
    total = q.count()
    items = q.order_by(Channel.category, Channel.name).offset((page - 1) * per_page).limit(per_page).all()
    return {"total": total, "page": page, "per_page": per_page,
            "items": [_channel_dict(c) for c in items]}


@app.put("/api/channels/{cid}")
def update_channel(cid: int, body: ChannelPatch, db: Session = Depends(get_db)):
    c = db.get(Channel, cid)
    if not c:
        raise HTTPException(404, "channel not found")
    if body.name is not None and body.name.strip():
        c.name = body.name.strip()
        c.norm_name = normalize_name(c.name)
    if body.category is not None:
        c.category = body.category.strip() or "未分类"
    if body.enabled is not None:
        c.enabled = body.enabled
    db.commit()
    return {"ok": True}


@app.delete("/api/channels/{cid}")
def delete_channel(cid: int, db: Session = Depends(get_db)):
    c = db.get(Channel, cid)
    if not c:
        raise HTTPException(404, "channel not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


class BatchIn(BaseModel):
    ids: list[int]
    op: str  # delete | enable | disable | set_category | merge
    category: str | None = None


@app.post("/api/channels/batch")
def batch_channels(body: BatchIn, db: Session = Depends(get_db)):
    ids = body.ids
    if not ids:
        return {"ok": True, "affected": 0}
    if body.op == "delete":
        n = db.query(Channel).filter(Channel.id.in_(ids)).delete(synchronize_session=False)
    elif body.op == "enable":
        n = db.query(Channel).filter(Channel.id.in_(ids)).update({"enabled": True})
    elif body.op == "disable":
        n = db.query(Channel).filter(Channel.id.in_(ids)).update({"enabled": False})
    elif body.op == "set_category":
        n = db.query(Channel).filter(Channel.id.in_(ids)).update(
            {"category": (body.category or "").strip() or "未分类"})
    elif body.op == "merge":
        # 同名合并：保留第一个，其余地址收为备用源后删除
        chans = db.query(Channel).filter(Channel.id.in_(ids)).order_by(Channel.id).all()
        if len(chans) < 2:
            raise HTTPException(400, "至少选择 2 个频道才能合并")
        keep = chans[0]
        try:
            backups = json.loads(keep.backup_urls or "[]")
        except Exception:
            backups = []
        for c in chans[1:]:
            if c.url and c.url not in backups and c.url != keep.url:
                backups.append(c.url)
            db.delete(c)
        keep.backup_urls = json.dumps(backups, ensure_ascii=False)
        n = len(chans) - 1
        db.commit()
        return {"ok": True, "affected": n, "kept_id": keep.id, "backups": len(backups)}
    else:
        raise HTTPException(400, f"unknown op: {body.op}")
    db.commit()
    return {"ok": True, "affected": n}


@app.get("/api/duplicates")
def list_duplicates(db: Session = Depends(get_db)):
    """按归一化名分组，返回有重复的组（只看启用频道，可选含禁用）。"""
    rows = (
        db.query(Channel.norm_name, func.count(Channel.id))
        .group_by(Channel.norm_name)
        .having(func.count(Channel.id) > 1)
        .order_by(func.count(Channel.id).desc())
        .limit(200)
        .all()
    )
    groups = []
    for norm, cnt in rows:
        chans = db.query(Channel).filter(Channel.norm_name == norm).order_by(Channel.id).all()
        groups.append({"norm_name": norm, "count": cnt,
                       "channels": [_channel_dict(c) for c in chans]})
    return {"groups": groups, "total_groups": len(groups)}


@app.get("/api/categories")
def list_categories(db: Session = Depends(get_db)):
    rows = (
        db.query(Channel.category, func.count(Channel.id))
        .group_by(Channel.category)
        .order_by(Channel.category)
        .all()
    )
    return [{"name": r[0] or "未分类", "count": r[1]} for r in rows]


@app.get("/api/stats")
def stats(db: Session = Depends(get_db)):
    return {
        "channels": db.query(Channel).count(),
        "enabled": db.query(Channel).filter(Channel.enabled == True).count(),  # noqa: E712
        "sources": db.query(Source).count(),
        "playlists": db.query(Playlist).count(),
    }


# ---------- 输出订阅 ----------
class PlaylistIn(BaseModel):
    name: str
    categories: list[str] = []
    search: str = ""
    source_ids: list[int] = []
    only_enabled: bool = True
    include_backups: bool = False  # 输出时把备用源也作为独立条目附上


PLAYLIST_TOKEN = os.environ.get("PLAYLIST_TOKEN", "").strip()


def _check_token(token: str = ""):
    if PLAYLIST_TOKEN and token != PLAYLIST_TOKEN:
        raise HTTPException(403, "invalid token")


def _expand_backups(channels: list, include: bool) -> list:
    """把备用地址展开为独立条目（原名 + [备用N]）。"""
    if not include:
        return channels
    from types import SimpleNamespace
    out = list(channels)
    for c in channels:
        try:
            backups = json.loads(c.backup_urls or "[]")
        except Exception:
            backups = []
        for i, u in enumerate(backups, 1):
            out.append(SimpleNamespace(
                name=f"{c.name} [备用{i}]", url=u, logo=c.logo,
                tvg_id=c.tvg_id, category=c.category,
            ))
    return out


def _apply_filters(q, f: dict):
    if f.get("only_enabled", True):
        q = q.filter(Channel.enabled == True)  # noqa: E712
    if f.get("categories"):
        q = q.filter(Channel.category.in_(f["categories"]))
    if f.get("search"):
        like = f"%{f['search']}%"
        q = q.filter(or_(Channel.name.like(like), Channel.orig_name.like(like)))
    if f.get("source_ids"):
        q = q.filter(Channel.source_id.in_(f["source_ids"]))
    return q.order_by(Channel.category, Channel.name)


@app.get("/api/playlists")
def list_playlists(db: Session = Depends(get_db)):
    return [
        {"id": p.id, "name": p.name, "filters": json.loads(p.filters or "{}")}
        for p in db.query(Playlist).order_by(Playlist.id).all()
    ]


@app.post("/api/playlists")
def create_playlist(body: PlaylistIn, db: Session = Depends(get_db)):
    p = Playlist(name=body.name.strip(), filters=json.dumps({
        "categories": body.categories, "search": body.search,
        "source_ids": body.source_ids, "only_enabled": body.only_enabled,
        "include_backups": body.include_backups,
    }, ensure_ascii=False))
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"id": p.id}


@app.put("/api/playlists/{pid}")
def update_playlist(pid: int, body: PlaylistIn, db: Session = Depends(get_db)):
    p = db.get(Playlist, pid)
    if not p:
        raise HTTPException(404, "playlist not found")
    p.name = body.name.strip()
    p.filters = json.dumps({
        "categories": body.categories, "search": body.search,
        "source_ids": body.source_ids, "only_enabled": body.only_enabled,
        "include_backups": body.include_backups,
    }, ensure_ascii=False)
    db.commit()
    return {"ok": True}


@app.delete("/api/playlists/{pid}")
def delete_playlist(pid: int, db: Session = Depends(get_db)):
    p = db.get(Playlist, pid)
    if not p:
        raise HTTPException(404, "playlist not found")
    db.delete(p)
    db.commit()
    return {"ok": True}


@app.get("/p/{pid}.m3u")
def serve_playlist(pid: int, token: str = "", db: Session = Depends(get_db)):
    _check_token(token)
    p = db.get(Playlist, pid)
    if not p:
        raise HTTPException(404, "playlist not found")
    f = json.loads(p.filters or "{}")
    channels = _apply_filters(db.query(Channel), f).all()
    channels = _expand_backups(channels, f.get("include_backups", False))
    disp = "inline; filename*=UTF-8''" + quote(f"{p.name}.m3u")
    return PlainTextResponse(build_m3u(channels, p.name),
                             media_type="audio/x-mpegurl",
                             headers={"Content-Disposition": disp})


@app.get("/playlist.m3u")
def serve_adhoc(category: str = "", search: str = "", source_id: int = 0,
                include_backups: bool = False, token: str = "",
                db: Session = Depends(get_db)):
    """即时订阅：/playlist.m3u?category=央视&search=新闻"""
    _check_token(token)
    f: dict = {"only_enabled": True}
    if category:
        f["categories"] = [c.strip() for c in category.split(",") if c.strip()]
    if search:
        f["search"] = search
    if source_id:
        f["source_ids"] = [source_id]
    channels = _apply_filters(db.query(Channel), f).all()
    channels = _expand_backups(channels, include_backups)
    return PlainTextResponse(build_m3u(channels), media_type="audio/x-mpegurl")


# ---------- 静态 UI ----------
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
