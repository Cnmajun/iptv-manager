"""数据模型：订阅源 / 频道 / 输出配置。"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from .db import Base


class Source(Base):
    """上游 M3U 订阅源。"""
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    url = Column(Text, nullable=False)
    enabled = Column(Boolean, default=True)
    interval_hours = Column(Integer, default=12)  # 抓取间隔（小时）
    last_fetch = Column(DateTime, nullable=True)
    last_status = Column(String(32), default="never")  # ok / error / never
    last_message = Column(String(512), default="")
    channel_count = Column(Integer, default=0)


class Channel(Base):
    """频道。name 为展示名（可改），orig_name 为源站原名。"""
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True)
    name = Column(String(256), nullable=False, index=True)
    norm_name = Column(String(256), nullable=False, index=True)  # 归一化名，用于同名合并
    orig_name = Column(String(256), default="")
    url = Column(Text, nullable=False)
    logo = Column(Text, default="")
    tvg_id = Column(String(256), default="")
    category = Column(String(128), default="", index=True)  # 归类（可改）
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True)
    source_name = Column(String(128), default="")
    enabled = Column(Boolean, default=True, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow)
    # 合并时保留下来的备用播放地址（JSON 数组），主源失效可手动切换
    backup_urls = Column(Text, default="[]")


class Playlist(Base):
    """可定制的输出订阅配置。"""
    __tablename__ = "playlists"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    # 过滤条件 JSON：{"categories": [...], "search": "...", "only_enabled": true, "source_ids": [...]}
    filters = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
