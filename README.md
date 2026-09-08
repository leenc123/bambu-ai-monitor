# Bambu AI Print Monitor

[![GitHub Tag](https://img.shields.io/github/v/tag/leenc123/bambu-ai-monitor?label=version)](https://github.com/leenc123/bambu-ai-monitor)
[![Open in Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=leenc123&repository=bambu-ai-monitor&category=integration)

Home Assistant 自定义集成，通过 YOLOv8 视觉 AI 实时监测拓竹（Bambu Lab）3D 打印异常，连续确认后自动暂停防止打印失败。

> **当前版本**: 0.2.1

## 功能

- **AI 实时监测**：通过打印机摄像头截取画面，YOLOv8 ONNX 本地推理分析
- **异常检测**：炒面/拉丝（Spaghetti）—— 模型脱落、首层粘附失败等
- **连续确认机制**：连续 N 帧（默认 2 次）检测到异常且置信度超过阈值才触发暂停，有效防误报
- **自动暂停**：达到连续检测阈值后自动暂停打印（可单独开关）
- **本地推理**：YOLO ONNX 模型在宿主机本地运行，**无需云端 API**，零费用
- **推理服务免手动部署**（无宿主机 systemd）：
  - 有 `/var/run/docker.sock` → **全自动**拉起侧车容器，零操作
  - 无 socket（HA OS）→ 去 Add-on Store 安装一次“Bambu Inference”，纯 UI 点击
- **MQTT 智能重连**：TCP Ping 探测 + 阶梯退避（10s → 30s → 60s → 5min）
- **实时状态**：打印进度、热床/喷嘴温度、剩余时间、层进度
- **异常标注画面**：摄像头实体显示 YOLO 检测框标注结果

## 系统架构

```
┌──────────────────────────────────────────┐
│  Home Assistant（Docker / HA OS）         │
│                                           │
│  ┌───────────────────────────────────┐   │
│  │ Bambu AI Monitor 集成              │   │
│  │                                   │   │
│  │  MQTT ←→ 拓竹打印机 (状态/命令)   │   │
│  │  TLS :6000 ←→ 打印机摄像头 (快照)  │   │
│  │  HTTP ←→ 推理服务 (YOLO 分析)     │   │
│  │                                   │   │
│  │  ┌─ service_manager.py ────────┐ │   │
│  │  │  Docker socket → 拉起侧车容器 │ │   │
│  │  │   bambu-ai-inference (Debian) │ │   │
│  │  │  无 socket → 提示装 Add-on    │ │   │
│  │  │   （配置流 inference 步骤）   │ │   │
│  │  └─────────────────────────────┘ │   │
│  └───────────────────────────────────┘   │
│                     │                     │
│                     ▼ HTTP :19530         │
│  ┌───────────────────────────────────┐   │
│  │  推理服务 (侧车容器 / Add-on)       │   │
│  │  YOLOv8 ONNX Runtime             │   │
│  │  RestartPolicy=always / 开机自启  │   │
│  │  /analyze   → JSON 检测结果      │   │
│  │  /visualize → 标注框 JPEG        │   │
│  │  /health    → 健康检查           │   │
│  └───────────────────────────────────┘   │
└──────────────────────────────────────────┘
```

## 安装

### 前提条件

1. **拓竹打印机**：X1C / X1E / P1P / P1S / A1 / A1 Mini（需开启 LAN 模式）
2. **打印机 LAN Access Code**：打印机屏幕 → 设置 → 网络 → LAN 中查看
3. **YOLO ONNX 模型文件**：`best.onnx` 已随插件打包在 `model/` 目录中

### 通过 HACS 安装（推荐）

1. 在 Home Assistant 中打开 HACS → 集成
2. 点击右上角菜单 → **自定义存储库**
3. 仓库地址：`https://github.com/leenc123/bambu-ai-monitor`，类别选择 **集成**
4. 添加后搜索 **Bambu AI Print Monitor** 并安装
5. 重启 Home Assistant

### 手动安装

```bash
# 将插件目录复制到 HA 的 custom_components
cp -r custom_components/bambu_ai_monitor <ha_config>/custom_components/

# 重启 HA
```

模型文件 `best.onnx` 已包含在 `model/` 目录中，无需额外下载。

## 配置

### 添加集成

Home Assistant → 设置 → 设备与服务 → 添加集成 → 搜索 **Bambu AI Print Monitor**

| 配置项 | 说明 |
|--------|------|
| 打印机 IP 地址 | 打印机局域网 IP |
| 局域网访问码 | 打印机屏幕上显示的 Access Code |
| 打印机序列号（可选） | 留空自动检测 |
| 打印机型号 | X1C / X1E / P1P / P1S / A1 / A1 Mini |
| 摄像头端口 | 默认 `6000`（A1 Mini / P1P 用） |
| YOLO ONNX 模型路径 | 默认 `model/best.onnx` |
| 推理服务器地址 | 默认 `localhost` |
| 推理服务器端口 | 默认 `19530` |

### 分析选项（配置完成后可随时修改）

| 选项 | 说明 |
|------|------|
| 分析间隔 | 30秒 / 1分钟 / **5分钟** / 10分钟 / 30分钟 |
| 置信度阈值 | 0.1 ~ 1.0（推荐 **0.5**） |
| 异常时自动暂停 | 开/关（默认 **开**） |
| 触发暂停的连续检测次数 | 1 ~ 5 次（推荐 **2 次**，防误报） |
| 推理服务器地址 | 默认 `localhost` |
| 推理服务器端口 | 默认 `19530` |

### 推理服务部署

添加集成后，系统会自动检测推理服务是否运行，并按以下策略部署：

| 环境 | 行为 |
|------|------|
| **Docker + 挂载了 `/var/run/docker.sock`** | ✅ **全自动** — 通过 Docker API 拉起 `bambu-ai-inference` 侧车容器（`RestartPolicy: always`），模型自动同步到 `/config/bambu_ai_model`。用户无需任何操作 |
| **HA OS / Supervised（无 socket）** | 配置流出现 inference 提示页：去 Add-on Store 安装“Bambu Inference”并启动，回来点继续，一次 UI 点击 |
| **纯 Docker 无 socket**（CasaOS / BigBear 等，改不了 HA 容器挂载） | 手动启动侧车容器一次（见下节），`--restart always` 之后开机自启、崩溃自启 |

> **推荐挂载 Docker socket**（compose 加一行 `- /var/run/docker.sock:/var/run/docker.sock`），之后全程零操作。HA OS 用户用 Add-on，同样无 SSH/命令行。

安装完成后可在 Home Assistant 中查看 `binary_sensor.inference_server` 确认服务状态。

#### 手动启动侧车容器（一次性，仅纯 Docker 无 socket 环境）

```bash
# 1. 如之前装过旧版 systemd 服务，先停掉（否则 19530 端口冲突）：
sudo systemctl stop yolo-inference-server
sudo systemctl disable yolo-inference-server
sudo rm -f /etc/systemd/system/yolo-inference-server.service
sudo systemctl daemon-reload
sudo rm -rf /opt/bambu-ai-inference

# 2. 准备模型目录（从已安装的集成目录拷，或从 GitHub 拉）：
mkdir -p ~/bambu_ai_model
cp <ha_config>/custom_components/bambu_ai_monitor/model/best.onnx ~/bambu_ai_model/
# 或：curl -sSL -o ~/bambu_ai_model/best.onnx \
#   https://raw.githubusercontent.com/leenc123/bambu-ai-monitor/main/custom_components/bambu_ai_monitor/model/best.onnx

# 3. 启动侧车（一次即可，开机自启）：
docker run -d --name bambu-ai-inference --restart always \
  -p 19530:19530 -v ~/bambu_ai_model:/model:ro \
  -e MODEL_PATH=/model/best.onnx \
  ghcr.io/leenc123/bambu-inference:latest

# 4. 验证：
curl -s http://localhost:19530/health
# 应返回 {"status": "ok", ...}
```

> **bridge 网络注意**：CasaOS 类平台的 HA 容器一般是 bridge 模式，容器内的 `localhost` 到不了宿主机端口。先查 `docker inspect <ha容器名> --format '{{.HostConfig.NetworkMode}}'`，如果是 bridge，把集成选项里的“推理服务器地址”改成 `docker0` 网卡 IP（`ip addr show docker0`，一般是 `172.17.0.1`）或宿主机局域网 IP，不要填 `localhost`。

## 实体列表

### 传感器

| 实体 ID | 说明 |
|---------|------|
| `sensor.print_status` | 打印机状态：空闲 / 打印中 / 已暂停 / 已完成 / 已断开 |
| `sensor.print_progress` | 打印进度 0~100% |
| `sensor.bed_temperature` | 热床温度（℃） |
| `sensor.nozzle_temperature` | 喷嘴温度（℃） |
| `sensor.remaining_time` | 剩余时间（分钟） |
| `sensor.layer_progress` | 当前层 / 总层数 |
| `sensor.last_analysis` | 最近一次 AI 分析结果描述 |
| `sensor.anomaly_type` | 检测到的异常类型（炒面/拉丝） |

### 二元传感器

| 实体 ID | 说明 |
|---------|------|
| `binary_sensor.printer_online` | 打印机 MQTT 在线状态 |
| `binary_sensor.anomaly_detected` | 是否检测到打印异常（连续确认通过后变亮） |
| `binary_sensor.inference_server` | 推理服务是否运行中 |

### 控制

| 实体 ID | 类型 | 说明 |
|---------|------|------|
| `button.analyze_now` | 按钮 | 立即触发一次 AI 分析 |
| `switch.auto_pause` | 开关 | 异常自动暂停开关 |
| `select.analysis_interval` | 选择器 | AI 分析间隔（30秒 ~ 30分钟） |
| `number.confidence_threshold` | 数字（滑块） | 异常判定置信度阈值 0.1 ~ 1.0 |

### 摄像头

| 实体 ID | 说明 |
|---------|------|
| `camera.annotated_snapshot` | YOLO 检测标注画面（框出异常区域） |

## 服务

| 服务 | 说明 | 参数 |
|------|------|------|
| `bambu_ai_monitor.analyze_now` | 立即触发 AI 分析 | `entry_id`（可选，留空分析所有） |
| `bambu_ai_monitor.set_analysis_interval` | 修改分析间隔 | `entry_id`（可选），`interval`（必填：30/60/300/600/1800 秒） |

## 异常类型说明

| 类型 | 原因 | 处理建议 |
|------|------|----------|
| 🕸️ **Spaghetti**（炒面/拉丝） | 模型脱落、首层粘附失败、挤出不足 | 检查热床调平、Z 偏移、首层挤出倍数 |

## Debug 模式（模拟打印机）

无需真实打印机即可测试集成功能：

- **IP 地址**：填写 `mock` 或 `127.0.0.1`
- **Access Code**：填写 `DEBUG_MODE`
- 集成会模拟打印进度 0% → 100%，在特定进度区间模拟异常检测，方便验证自动暂停等全部功能

## 故障排查

### 开启详细日志

```yaml
logger:
  logs:
    custom_components.bambu_ai_monitor: debug
```

### MQTT 连接问题

| 日志 | 含义 |
|------|------|
| `MQTT on_connect called, rc=Success` | MQTT 连接成功 |
| `Unspecified error` 后立即断开 | 打印机不接受连接参数（检查 Access Code） |
| `TCP connected but no reply` | TCP 能连但打印机不发 CONNACK |
| `not reachable, deferring connect` | TCP Ping 不通，等待阶梯退避后重试 |

### 推理服务不可用

检查 `binary_sensor.inference_server`：

- 如果为 **off** 且 Docker socket 已挂载 → 等待约 1 分钟（首次拉镜像），`docker ps` 应能看到 `bambu-ai-inference`
- 如果为 **off** 且是 HA OS / Supervised → 去 设置 → Add-on → 安装并启动“Bambu Inference”（详见 `bambu_inference_addon/README.md`）
- 如果为 **off** 且是纯 Docker 无 socket（CasaOS / BigBear）→ 按上节手动起侧车；若 `docker ps` 看不到容器，先查旧 systemd 是否还占着 19530：`sudo systemctl status yolo-inference-server`，占着就按上节第 1 步清掉
- 如果侧车已在跑但集成连不上 → 检查 HA 容器网络模式：bridge 模式下“推理服务器地址”不能填 `localhost`，改填 `docker0` IP 或宿主机局域网 IP

### 摄像头无画面

- A1 Mini / P1P：TLS 端口 `6000`（插件已自动适配）
- X1/X1C：支持 RTSP / MJPEG
- 确认端口可达：`nc -zv <打印机IP> 6000`

## 许可证

MIT License
