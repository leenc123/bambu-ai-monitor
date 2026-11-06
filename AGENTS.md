# AGENTS.md — bambu-ai-monitor 协作约定

## 提交 / 打 tag 与 Issue 联动（强制）

1. 用户在本轮对话中明确提到的 issue 编号，必须全部出现在 commit message
   尾部，格式固定：`Fixes #1, Fixes #2, Fixes #3`
   （顺序与用户提及顺序一致；只写用户明确提到或确认修复的编号，不自行脑补）
2. 中文提交主体保持现有风格（`fix:` / `feat:` / `docs:` + 中文描述），
   keyword 行单独放在 message 尾部。
3. Tag（`v*`）只负责触发镜像构建，**不承担关闭 issue**；打 tag 前必须确认
   含 keyword 的 commit 已推送到 `main`（默认分支）。
4. 每次提交前，先在回复里贴出完整 message（含 `Fixes #N` 行）给用户确认。

## 版本与发布

- 版本号三处同步：`custom_components/bambu_ai_monitor/manifest.json`、
  `bambu_inference_addon/config.yaml`、`README.md`（当前版本）。
- 打 tag 即触发 `.github/workflows/build-inference-image.yml` 重建并推送
  `ghcr.io/leenc123/bambu-inference:latest` 与 `:vX.Y.Z`。
- 纯文档/约定类提交不需要打 tag（避免无意义重建镜像）。
- 推理服务改动生效需要用户侧 `docker pull` + 重建容器；
  HA 集成改动生效需要用户更新集成并重启 HA。
