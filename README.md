# 🎮 win_status_checker

专为游戏玩家设计的轻量级 Windows 系统状态监控工具，实时监控网络、GPU、输入设备状态。

A lightweight Windows system status monitoring tool designed for gamers. Real-time monitoring of network, GPU, and input device status.

---

## 功能 | Features

- **网络监控 | Network**：延迟、丢包率、上下行速率、连接状态
  Latency, packet loss, throughput, connection status
- **GPU 监控 | GPU**：使用率、显存、温度、功耗、驱动版本
  Usage, VRAM, temperature, power draw, driver version
- **输入设备监控 | Input Devices**：鼠标/键盘/耳机/手柄/蓝牙驱动状态，支持有线和无线
  Mouse / Keyboard / Headset / Controller / Bluetooth driver status, wired & wireless
- **Web 仪表盘 | Web Dashboard**：浏览器实时查看所有状态（WebSocket 推送）
  Real-time browser dashboard via WebSocket
- **智能报警 | Smart Alerts**：异常时 Windows 通知弹窗提醒，60 秒冷却不刷屏
  Windows toast notifications on anomaly, 60s cooldown to avoid spam
- **日志记录 | Logging**：所有异常可追溯
  All anomalies logged and traceable

---

## 系统要求 | Requirements

- Windows 10 / 11
- Python 3.10+（[下载](https://www.python.org/downloads/)，安装时勾选 "Add Python to PATH"）
- NVIDIA GPU（可选，有 nvidia-smi 可获取详细数据）| Optional, enables full GPU metrics via nvidia-smi
- Intel / AMD GPU 通过 Windows 性能计数器获取使用率 | Intel / AMD GPU usage via Windows performance counters

---

## 快速启动 | Quick Start

**1. 安装环境（只需一次）| Install (run once)**
```bash
python install.py
```
自动创建 `.venv` 虚拟环境并安装所有依赖，不影响系统 Python。

Creates a `.venv` with all dependencies. Your system Python stays clean.

**2. 启动服务 | Run**
```bash
python run.py              # 完整模式 | Full mode (monitor + web)
python run.py --no-web     # 仅监控报警 | Monitor & alert only
```

然后打开浏览器访问 | Then open browser: **http://localhost:8870**

---

## 设计原则 | Design Principles

| | 中文 | English |
|---|---|---|
| ⚡ | 不影响游戏：进程优先级"低于正常"，2s 采样 | Won't affect gaming: below-normal priority, 2s interval |
| 🔕 | 不刷屏：同类报警 60s 冷却 | No spam: 60s cooldown per alert type |
| 📝 | 可追溯：异常记录在 `logs/` | Traceable: anomalies logged in `logs/` |
| 🔌 | 支持无线：蓝牙 / 2.4G / USB 无线自动识别 | Wireless support: Bluetooth / 2.4G / USB wireless auto-detect |

---

## 配置 | Configuration

编辑 `config/config.py` 可调整 | Edit `config/config.py` to adjust:

- 监控频率 | Monitor interval
- 报警阈值（延迟、丢包、温度等）| Alert thresholds (latency, packet loss, temp, etc.)
- Web 端口 | Web port
- 进程优先级 | Process priority

---

## 测试 | Testing

```bash
python run.py --test
```

包含单元测试、集成测试、模拟驱动异常测试。

Includes unit tests, integration tests, and simulated driver failure tests.

---

## 文件结构 | Project Structure

```
win_status_checker/
├── install.py           # 环境安装（只需运行一次）| Setup (run once)
├── run.py               # 启动脚本 | Run script
├── requirements.txt     # Python 依赖 | Dependencies
├── config/
│   └── config.py        # 配置 | Configuration
├── src/
│   ├── main.py          # 主程序 | Main application
│   ├── alerter.py       # 报警模块 | Alert module
│   ├── static/
│   │   └── index.html   # Web 仪表盘 | Web dashboard
│   └── monitors/
│       ├── network_monitor.py   # 网络监控 | Network monitor
│       ├── gpu_monitor.py       # GPU 监控 | GPU monitor
│       └── driver_monitor.py    # 设备驱动监控 | Device driver monitor
├── tests/               # 测试用例 | Tests
├── logs/                # 日志（自动创建）| Logs (auto-created)
└── .venv/               # 虚拟环境（install.py 创建）| Virtual env
```

---

## License

MIT
