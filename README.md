# 📺 IPTV 订阅管理器

把网上收集的 IPTV（M3U）订阅源整合起来，定时自动更新，支持改名、删除、归类、同名合并，并输出可定制的订阅链接，供局域网内的播放器 / 机顶盒使用。

## 功能

- **多源聚合**：添加多个上游 M3U 订阅链接，每个源可单独设置更新间隔
- **定时更新**：按设定间隔自动抓取（默认 12 小时），也可手动"立即更新"；增量入库，不覆盖你改过的频道名和分类
- **改名**：直接在列表里改频道显示名（保留源站原名备查）
- **删除 / 禁用**：单个删除、批量删除，或仅禁用（不出现在输出订阅里）
- **归类**：自由填写分类，批量归类
- **同名合并**：自动按归一化频道名（忽略大小写、空格、高清/超清等后缀）找出重复，一键合并；被合并的播放地址保留为**备用源**，主源失效可手动切换，输出订阅可选"含备用源"
- **定制输出**：
  - 即时订阅：`/playlist.m3u?category=央视,卫视`（分类逗号分隔，支持 `search=` 关键词）
  - 保存的输出配置：`/p/{id}.m3u`，按分类/关键词组合，链接固定不变

## 快速上手（Docker）

```bash
docker compose up -d
```

然后浏览器打开 `http://<你的服务器IP>:8080`（局域网内把 IP 换成机器的局域网 IP，如 `http://192.168.1.10:8080`）。

数据保存在 `./data/iptv.db`（已挂载 volume，重建容器不丢失）。

## 可选：订阅链接加 token

局域网内如果不想被别人蹭订阅，可以设置环境变量 `PLAYLIST_TOKEN`（docker-compose.yml 里加一行 `- PLAYLIST_TOKEN=abc123`），之后所有 `/p/*.m3u` 和 `/playlist.m3u` 都必须带 `?token=abc123` 才能访问。不设置则无需 token。

## 在 OpenWrt 软路由上跑

1. 先装好 Docker（`dockerd` + `luci-app-dockerman`）
2. 把本项目传到软路由，`docker compose up -d`（或在 dockerman 里手动建容器，镜像 build 本地 Dockerfile，映射 8080 端口，挂载 `/data`）
3. 局域网设备用 `http://<软路由IP>:8080` 访问管理页，订阅链接填到播放器即可

## 本地开发运行

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | /api/sources | 订阅源列表 / 新增 |
| PUT/DELETE | /api/sources/{id} | 修改 / 删除（含其频道） |
| POST | /api/sources/{id}/refresh | 立即抓取 |
| GET | /api/channels | 频道列表（search/category/source_id/enabled/page） |
| PUT/DELETE | /api/channels/{id} | 改名/归类/启禁 / 删除 |
| POST | /api/channels/batch | 批量：delete/enable/disable/set_category/merge |
| GET | /api/duplicates | 同名重复分组 |
| GET | /api/categories | 分类及数量 |
| GET/POST | /api/playlists | 输出配置列表 / 新建 |
| GET | /p/{id}.m3u | 输出配置对应的订阅 |
| GET | /playlist.m3u | 即时订阅（category/search/source_id 参数） |

## 说明

- 抓取失败（源站挂了、超时）会在订阅源列表里标红提示，不影响已有数据
- 合并频道默认保留 ID 最小的一个，其余删除，操作前会二次确认
- 本项目只做订阅列表的聚合管理，不提供、不存储任何直播源内容
