# 🎮 win_status_checker

专为游戏玩家设计的轻量级 Windows 系统状态监控工具，实时监控网络、GPU、CPU、内存、输入设备状态。

A lightweight Windows system status monitoring tool designed for gamers. Real-time monitoring of network, GPU, CPU, memory, and input device status.

---

## 功能 | Features

- **网络监控 | Network**：延迟、丢包率、抖动(Jitter)、上下行速率、链路闪断检测、网卡错误包
  Latency, packet loss, jitter, throughput, link flap detection, NIC error packets
- **GPU 监控 | GPU**：使用率、显存、温度、功耗、驱动版本
  Usage, VRAM, temperature, power draw, driver version
- **CPU / 内存 / 磁盘 | System Resources**：CPU 使用率与降频检测、内存用量、磁盘 I/O、后台进程抢占检测
  CPU usage & throttle detection, memory, disk I/O, background process hogging
- **输入设备监控 | Input Devices**：鼠标/键盘/耳机/手柄/蓝牙驱动状态，支持有线和无线
  Mouse / Keyboard / Headset / Controller / Bluetooth driver status, wired & wireless
- **启动检测 | Startup Checks**：电源计划、显示器刷新率、待重启更新、内存容量（一次性）
  Power plan, display refresh rate, pending Windows updates, memory capacity (one-shot)
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
| 🛡️ | 启动预检：电源计划、刷新率、更新状态一次性检测 | Startup pre-check: power plan, refresh rate, pending updates |

---

## 报警项 | Alert Items

| 类别 | 报警条件 | 默认阈值 |
|------|---------|---------|
| 网络断开 | 连接丢失 | - |
| 丢包 | 丢包率过高 | > 5% |
| 延迟 | 延迟过高 | > 100ms |
| 抖动 | 网络不稳定 | > 30ms |
| GPU 过热 | 温度过高 | > 85°C |
| 显存不足 | 显存占用过高 | > 95% |
| 内存不足 | 系统内存占用过高 | > 90% |
| CPU 降频 | 频率低于最大值 70% | 自动检测 |
| 后台抢资源 | Windows Update / Defender 等高占用 | CPU > 15% |
| 驱动异常 | 鼠标/键盘/耳机/手柄驱动故障 | error_code ≠ 0 |
| 电源计划 | 非高性能模式（启动时） | 一次性 |
| 刷新率 | 低于预期（启动时） | < 120Hz |

---

## 配置 | Configuration

编辑 `config/config.py` 可调整 | Edit `config/config.py` to adjust:

- 监控频率 | Monitor interval
- 报警阈值（延迟、丢包、抖动、温度等）| Alert thresholds
- Web 端口 | Web port
- 进程优先级 | Process priority
- 启动检测参数（最低刷新率、最低内存）| Startup check params

---

## 测试 | Testing

```bash
python run.py --test
```

59 个测试用例，覆盖单元测试、集成测试、模拟异常测试。

59 test cases covering unit tests, integration tests, and simulated failure tests.

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
│   ├── startup_checks.py  # 启动时一次性检测 | One-shot startup checks
│   ├── static/
│   │   └── index.html   # Web 仪表盘 | Web dashboard
│   └── monitors/
│       ├── network_monitor.py   # 网络监控（含抖动/闪断）| Network (jitter/link flap)
│       ├── gpu_monitor.py       # GPU 监控 | GPU monitor
│       ├── system_monitor.py    # CPU/内存/磁盘/进程 | CPU/Mem/Disk/Process
│       └── driver_monitor.py    # 设备驱动监控 | Device driver monitor
├── tests/               # 测试用例（59个）| Tests (59 cases)
├── logs/                # 日志（自动创建）| Logs (auto-created)
└── .venv/               # 虚拟环境（install.py 创建）| Virtual env
```

---

## License

MIT
