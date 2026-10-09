# OpenCLIP Embedding Service (Docker)

本目录提供一个可本地运行的 OpenCLIP Embedding 服务，接口兼容 Indexed 需要的：

- `GET /v1/models`
- `POST /v1/embeddings`（请求体使用 `model + messages`）

> 说明：在 Apple Silicon 上通过 Docker 运行通常使用 CPU 推理，不会走 Metal/MPS。

## 1) 启动服务

```bash
cd /Users/hoyang/Code/indexed.worktrees/embedding-service-explanation/openclip-embedding-service
docker compose up -d --build
```

## 2) 查看状态与日志

```bash
docker ps --filter name=openclip-embedding
docker logs openclip-embedding --tail 100
```

## 3) 验证 API

```bash
curl -sS http://127.0.0.1:5007/health
curl -sS http://127.0.0.1:5007/v1/models
```

文本 embedding 示例：

```bash
curl -sS http://127.0.0.1:5007/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"openclip-vit-l-14",
    "messages":[{"role":"user","content":[{"type":"text","text":"a red sports car"}]}]
  }'
```

图片（base64 data URI）embedding 示例：

```bash
curl -sS http://127.0.0.1:5007/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"openclip-vit-l-14",
    "messages":[{"role":"user","content":[{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,<BASE64>"}}]}]
  }'
```

图片（容器挂载的本机文件路径）embedding 示例：

```bash
curl -sS http://127.0.0.1:5007/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"openclip-vit-l-14",
    "messages":[{"role":"user","content":[{"type":"image_url","image_url":{"url":"file:///mnt/indexed-assets/demo/cat.jpg"}}]}]
  }'
```

## 4) 给 Indexed 的建议配置

- 向量后端：外部 Embedding 服务
- Embedding 服务地址：`http://127.0.0.1:5007`
- 模型：`openclip-vit-l-14`
- 向量维度：`768`
- 输入格式：`auto`
- 数据库目录：可留空（使用 Indexed 默认路径）
- 向量空间：可留空（由 Indexed 自动生成）

## 5) 可调环境变量

见 [docker-compose.yml](/Users/hoyang/Code/indexed.worktrees/embedding-service-explanation/openclip-embedding-service/docker-compose.yml)：

- `MODEL_NAME`（默认 `ViT-L-14`）
- `PRETRAINED`（默认 `openai`）
- `SERVED_MODEL_ID`（默认 `openclip-vit-l-14`）
- `HTTP_TIMEOUT_SECONDS`（默认 `20`）
- `LOCAL_IMAGE_ROOTS`（默认 `/mnt/indexed-assets`；多个目录可用 `:` 或 `,` 分隔）
- `FUSION_MODE`（`adaptive` 或 `fixed`）
- `FIXED_IMAGE_WEIGHT` / `FIXED_TEXT_WEIGHT`（`fixed` 模式下生效）
- `ADAPTIVE_TEXT_WEIGHT_MIN` / `ADAPTIVE_TEXT_WEIGHT_MAX` / `ADAPTIVE_TEXT_WEIGHT_SLOPE`（`adaptive` 模式下生效）

## 6) 本地文件挂载（image_url 读本机图片）

当前 compose 默认挂载：

- 主机目录：`${INDEXED_LOCAL_ASSETS_DIR:-./mounted-assets}`
- 容器目录：`/mnt/indexed-assets`（只读）
- 默认情况下 `INDEXED_LOCAL_ASSETS_DIR` 会在 compose 中解析为 `./mounted-assets`（相对 [docker-compose.yml](/Users/hoyang/Code/indexed.worktrees/embedding-service-explanation/openclip-embedding-service/docker-compose.yml) 所在目录）。

做法：

1. 在本目录放要测试的图片：`./mounted-assets/demo/cat.jpg`
2. 或者在启动前指定主机素材目录：

```bash
export INDEXED_LOCAL_ASSETS_DIR="/Users/hoyang/Pictures"
docker compose up -d --build
```

3. 请求里传 `file:///mnt/indexed-assets/...` 路径。

> 服务会按 `LOCAL_IMAGE_ROOTS` 做白名单校验，白名单外路径会返回 403。

## 7) 停止服务

```bash
docker compose down
```

## 8) 备份清单（原始素材 vs 向量库）

以下目录按「恢复价值」排序：

1. **原始素材目录（必须）**
   - 你在 Indexed 中添加的图片 / 视频 / 文档所在目录
   - 这些是源文件本体，向量库不能替代原始素材

2. **Indexed 配置文件（必须）**
   - 默认：`$HOME/.config/indexed/config.json`
   - 若设置了 `INDEXED_HOME`：`$INDEXED_HOME/config/config.json`

3. **Indexed 向量库目录（强烈建议）**
   - 默认：`$HOME/.local/share/indexed/zvec`
   - 若设置了 `INDEXED_HOME`：`$INDEXED_HOME/data/zvec`
   - 不备份也能重建，但重扫和重算 embedding 耗时较长

4. **Indexed 状态目录（可选）**
   - 默认：`$HOME/.local/state/indexed/`
   - 若设置了 `INDEXED_HOME`：`$INDEXED_HOME/state/`
   - 包含性能历史等运行状态，不是核心数据

5. **本服务目录（可选）**
   - `$HOME/Code/indexed.worktrees/embedding-service-explanation/openclip-embedding-service`
   - 主要是部署脚本和配置，随时可从仓库恢复；若有自定义改动建议一并备份
