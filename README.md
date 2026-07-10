# Bambu AI Print Monitor

[![GitHub Tag](https://img.shields.io/github/v/tag/leenc123/bambu-ai-monitor?label=version)](https://github.com/leenc123/bambu-ai-monitor)
[![Open in Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=leenc123&repository=bambu-ai-monitor&category=integration)

Home Assistant 自定义集成，通过 YOLO 视觉 AI 实时监测拓竹（Bambu Lab）3D 打印异常，自动暂停防止打印失败。

## 功能

- **AI 实时监测**：通过打印机摄像头截取画面，YOLOv8 ONNX 本地推理分析
- **异常检测**：炒面/拉丝（Spaghetti）、拉丝溢出（Stringing）、疙瘩（Zits）
- **自动暂停**：连续检测到异常时自动暂停打印（可配置连续确认次数）
- **本地推理**：YOLO ONNX 模型在宿主机本地运行，**无需云端 API**，零费用
- **推理服务自动部署**（Docker 环境）：
  - 挂载了 Docker socket → **全自动**安装依赖、创建 systemd 服务、启动
  - 未挂载 Docker socket → 自动写安装脚本到 `/config/`，用户跑一次命令
- **MQTT 智能重连**：TCP Ping 探测 + 阶梯退避（10s → 30s → 60s → 5min）
- **实时状态**：打印进度、温度、剩余时间、层进度、异常标注画面

## 系统架构

```
┌─────────────────────────────────────────┐
│  Home Assistant（Docker / HA OS）        │
│                                          │
│  ┌──────────────────────────────────┐   │
│  │ Bambu AI Monitor 集成             │   │
│  │                                  │   │
│  │  MQTT ←→ 拓竹打印机 (状态/命令)  │   │
│  │  TLS 6000 ←→ 打印机摄像头 (快照) │   │
│  │  HTTP ←→ 推理服务 (YOLO 分析)    │   │
│  │                                  │   │
│  │  ┌─ service_manager.py ───────┐ │   │
│  │  │  Docker socket → 自动安装   │ │   │
│  │  │  无 socket  → 写脚本到共享  │ │   │
│  │  │               目录          │ │   │
│  │  └────────────────────────────┘ │   │
│  └──────────────────────────────────┘   │
│                    │                     │
│                    ▼ HTTP :19530         │
│  ┌──────────────────────────────────┐   │
│  │ 推理服务 (宿主机 systemd)         │   │
│  │  YOLOv8 ONNX Runtime            │   │
│  │  开机自启 / 崩溃自动重启         │   │
│  │  /analyze  → JSON 检测结果      │   │
│  │  /visualize → 标注框 JPEG       │   │
│  │  /health    → 健康检查          │   │
│  └──────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

## 安装

### 前提条件

1. **拓竹打印机**：X1C / X1E / P1P / P1S / A1 / A1 Mini（需开启 LAN 模式）
2. **打印机 LAN Access Code**：在打印机屏幕 设置 → 网络 → LAN 中查看
3. **YOLO ONNX 模型**：导出 `best.onnx` 放到 `custom_components/bambu_ai_monitor/model/` 目录

### 通过 HACS 安装

1. 将本仓库添加到 HACS 自定义仓库
2. 在 HACS 中搜索 "Bambu AI Print Monitor" 并安装
3. 重启 Home Assistant

### 手动安装

```bash
cp -r custom_components/bambu_ai_monitor <ha_config>/custom_components/
cp best.onnx <ha_config>/custom_components/bambu_ai_monitor/model/
# 重启 HA
```

## 配置

### 添加集成

Home Assistant → 设置 → 设备与服务 → 添加集成 → 搜索 "Bambu AI Print Monitor"

| 字段 | 说明 |
|------|------|
| 打印机 IP 地址 | 打印机局域网 IP |
| 局域网访问码 | 打印机屏幕上显示的 Access Code |
| 打印机序列号 | 可选，不填自动检测 |
| 打印机型号 | X1C / X1E / P1P / P1S / A1 / A1 Mini |
| 摄像头端口 | 默认 6000（A1 Mini/P1P 用） |
| YOLO ONNX 模型路径 | 默认 `model/best.onnx` |
| 推理服务器地址 | 默认 `127.0.0.1` |
| 推理服务器端口 | 默认 `19530` |

分析选项（可在后期随时修改）：
- **分析间隔**：30秒 ~ 30分钟
- **置信度阈值**：0.1 ~ 1.0（推荐 0.5）
- **异常自动暂停**：检测到异常时自动暂停
- **连续检测次数**：触发暂停前的连续确认次数（推荐 2 次，防误报）

### 推理服务部署

插件会自动检测推理服务是否运行，按以下策略部署：

| 环境 | 行为 |
|------|------|
| **Docker + 挂载了 `/var/run/docker.sock`** | ✅ **全自动** — 通过 Docker API 在宿主机安装依赖、创建 systemd、启动服务 |
| **Docker + 未挂载 socket** | 写安装脚本到 `/config/install_inference_server.sh`，用户跑一次：`bash /config/install_inference_server.sh` |
| **HA OS（虚拟机/物理机）** | 同上，脚本写到 `/config/` 目录 |

> 推荐挂载 Docker socket，实现零手动操作。

## 实体列表

### 传感器

| 实体 | 说明 |
|------|------|
| `sensor.print_status` | 打印状态：空闲 / 打印中 / 暂停 / 已完成 |
| `sensor.print_progress` | 打印进度 0~100% |
| `sensor.bed_temperature` | 热床温度 |
| `sensor.nozzle_temperature` | 喷嘴温度 |
| `sensor.remaining_time` | 剩余时间（分钟） |
| `sensor.layer_progress` | 当前层 / 总层数 |
| `sensor.last_analysis` | 最近 AI 分析结果描述 |
| `sensor.anomaly_type` | 检测到的异常类型 |

### 二元传感器

| 实体 | 说明 |
|------|------|
| `binary_sensor.printer_online` | 打印机 MQTT 在线状态 |
| `binary_sensor.anomaly_detected` | 是否检测到打印异常 |
| `binary_sensor.inference_server` | 推理服务是否运行中 |

### 控制

| 实体 | 类型 | 说明 |
|------|------|------|
| `button.analyze_now` | 按钮 | 立即触发 AI 分析 |
| `switch.auto_pause` | 开关 | 异常自动暂停开关 |
| `select.analysis_interval` | 选择器 | AI 分析间隔 |
| `number.confidence_threshold` | 数字 | 异常判定置信度阈值 |

### 摄像头

| 实体 | 说明 |
|------|------|
| `camera.annotated_snapshot` | YOLO 检测标注画面（框出异常区域） |

## 服务

| 服务 | 说明 | 参数 |
|------|------|------|
| `bambu_ai_monitor.analyze_now` | 立即触发 AI 分析 | `entry_id`（可选） |
| `bambu_ai_monitor.set_analysis_interval` | 修改分析间隔 | `entry_id`（可选）, `interval`（秒） |

## 异常类型说明

| 类型 | 原因 | 处理建议 |
|------|------|----------|
| 🕸️ **Spaghetti**（炒面） | 模型脱落、首层粘附失败 | 检查热床调平、首层 Z 偏移 |
| 🧵 **Stringing**（拉丝） | 回抽设置不当、温度过高 | 调整回抽距离/速度、降低温度 |
| 🎯 **Zits**（疙瘩） | 压力提前/回抽补偿不准 | 校准挤出倍数、线性压力提前 |

## Debug 模式（模拟打印机）

- **IP 地址**：`mock` 或 `127.0.0.1`
- **Access Code**：`DEBUG_MODE`
- 模拟打印进度 0% → 100%，在特定区间模拟异常

## 故障排查

### MQTT 连接不上

```yaml
logger:
  logs:
    custom_components.bambu_ai_monitor: debug
```

| 日志 | 含义 |
|------|------|
| `MQTT on_connect called, rc=Success` | MQTT 连接成功 |
| `Unspecified error` 后立即断开 | 打印机不接受连接参数 |
| `TCP connected but no reply` | TCP 能连但打印机不发 CONNACK |
| `not reachable, deferring connect` | TCP Ping 不通，等退避重试 |

### 推理服务不可用

```
Inference server not reachable
```

解决：检查 `binary_sensor.inference_server`，如果为 off 且 Docker socket 未挂载，在宿主机执行：

```bash
bash /config/install_inference_server.sh
```

### 摄像头无画面

- A1 Mini / P1P：TLS 端口 6000（插件已自动适配）
- X1/X1C：支持 RTSP
- 确认端口可达：`nc -zv <打印机IP> 6000`

## 许可证

MIT License
