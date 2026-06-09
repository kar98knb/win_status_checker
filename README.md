# 🎮 win_status_checker

专为游戏玩家设计的轻量级 Windows 系统状态监控工具。后台静默运行，异常时弹窗报警，崩溃后自动生成分析报告。

A lightweight Windows system monitor for gamers. Runs silently in background, alerts on anomalies, generates crash analysis reports.

---

## 功能 | Features

- **网络监控 | Network**：延迟、丢包、抖动(Jitter)、链路闪断、网卡错误包、基线突变检测
  Latency, packet loss, jitter, link flap detection, NIC errors, baseline anomaly detection
- **GPU 监控 | GPU**：使用率、显存、温度、驱动版本
  Usage, VRAM, temperature, driver version
- **CPU / 内存 / 磁盘 | System**：使用率、降频检测、磁盘 I/O、后台进程抢占检测
  CPU usage & throttle detection, memory, disk I/O, background process hogging
- **输入设备 | Devices**：鼠标/键盘/耳机/手柄/蓝牙驱动状态，有线 & 无线
  Mouse / Keyboard / Headset / Controller / Bluetooth, wired & wireless
- **进程焦点 | Process Focus**：自动锁定高占用进程（游戏），追踪其状态直到退出
  Auto-locks high-usage process (game), tracks until exit
- **启动检测 | Startup Checks**：电源计划、刷新率、待重启更新、内存容量
  Power plan, refresh rate, pending updates, memory capacity
- **事件日志回溯 | Event Log**：重启后读取 Windows 事件日志，定位 GPU TDR / 蓝屏 / 意外关机
  Post-reboot Windows event log analysis for GPU TDR / BSOD / unexpected shutdown
- **崩溃追溯 | Crash Recovery**：快照每 2s 落盘，系统 hang 后重启也能回溯最后状态
  Snapshot fsynced every 2s, last system state recoverable after hard power-off
- **智能报警 | Alerts**：Windows 通知弹窗，60s 冷却不刷屏，基线自适应减少误报
  Windows toast notifications, 60s cooldown, baseline-adaptive to reduce false alarms
- **历史分析 | Analysis**：列出历史会话，对比任意两次运行的日志，找出差异
  List sessions, diff any two runs, highlight anomalies

---

## 系统要求 | Requirements

- Windows 10 / 11
- Python 3.10+（[下载](https://www.python.org/downloads/)，安装时勾选 "Add Python to PATH"）
  [Download](https://www.python.org/downloads/), check "Add Python to PATH" during install

---

## 快速启动 | Quick Start

```bash
python install.py          # 安装环境（只需一次）| Install (once)
python run.py              # 启动监控 | Start monitoring
```

---

## 命令 | Commands

| 命令 | 说明 | Description |
|------|------|-------------|
| `python run.py` | 启动监控（Ctrl+C 退出时生成报告） | Start monitor (report on Ctrl+C) |
| `python run.py --list` | 列出历史会话 | List past sessions |
| `python run.py --analyze 0 1` | 对比两份历史日志 | Diff two sessions |
| `python run.py --test` | 运行测试套件（100 个用例） | Run tests (100 cases) |

---

## 设计原则 | Design Principles

| | 中文 | English |
|---|---|---|
| ⚡ | 不影响游戏：进程优先级"低于正常"，2s 采样 | Below-normal priority, 2s interval |
| 🧵 | 各模块独立线程，互不阻塞 | Each monitor in its own thread |
| 🔕 | 同类报警 60s 冷却 + 基线突变检测减少误报 | 60s cooldown + baseline anomaly detection |
| 📝 | 每次运行独立日志目录，模块日志分文件 | Per-session dir, per-module log files |
| 💾 | 快照每 2s fsync 落盘，系统 hang 也不丢数据 | Snapshot fsynced every 2s, survives hard power-off |

---

## 日志结构 | Log Structure

```
logs/
├── last_snapshot.json              # 运行时快照（跨会话）| Runtime snapshot (cross-session)
└── 20260609_163732/                # 本次会话 | This session
    ├── monitor.log                 # 全局日志 | Global log
    ├── report.txt                  # Ctrl+C 退出时的汇总报告 | Summary on exit
    ├── crash_report.json           # 异常退出分析（如有）| Crash analysis (if any)
    └── log/                        # 各模块独立日志 | Per-module logs
        ├── network.log
        ├── gpu.log
        ├── system.log
        ├── drivers.log
        └── focus.log
```

---

## 报警项 | Alerts

| 类别 Category | 条件 Condition | 阈值 Threshold |
|------|------|------|
| 网络断开 Network down | 连接丢失 Connection lost | - |
| 延迟突增 Latency spike | 偏离基线 3σ Deviation > 3σ | 自适应 Adaptive |
| 抖动突增 Jitter spike | 偏离基线 3σ Deviation > 3σ | 自适应 Adaptive |
| 丢包 Packet loss | 丢包率过高 Too high | > 5% |
| GPU 过热 GPU overheat | 温度过高 Temp too high | > 85°C |
| 显存不足 VRAM low | 占用过高 Usage too high | > 95% |
| 内存不足 Memory low | 系统内存高 System mem high | > 90% |
| CPU 降频 CPU throttle | 频率 < 最大值 70% Freq < 70% max | 自动 Auto |
| 后台抢资源 Resource hog | 已知高占用进程 Known hog process | CPU > 15% |
| 驱动异常 Driver error | 设备驱动故障 Device driver fault | error_code ≠ 0 |
| 电源计划 Power plan | 非高性能 Not high-perf (startup) | 一次性 One-shot |

---

## 配置 | Configuration

编辑 `config/config.py` | Edit `config/config.py`:

- 监控频率 | Monitor interval
- 报警阈值（延迟、丢包、温度等）| Alert thresholds (latency, loss, temp, etc.)
- 日志保留天数 | Log retention days
- 进程焦点白名单 | Process focus whitelist
- 进程优先级 | Process priority

---

## 文件结构 | Project Structure

```
win_status_checker/
├── install.py           # 环境安装 | Setup
├── run.py               # 入口脚本 | Entry point
├── requirements.txt     # 依赖 | Dependencies
├── config/
│   └── config.py        # 配置 | Configuration
├── src/
│   ├── main.py          # 主程序 | Main
│   ├── analyzer.py      # 历史日志分析 | Log analysis
│   ├── alerts/          # 报警 & 快照 | Alerts & snapshot
│   ├── checks/          # 启动检测 & 事件日志 | Startup checks & event log
│   ├── compat/          # 平台适配 | Platform compat
│   └── monitors/        # 各监控模块 | Monitor modules
│       ├── network_monitor.py   # 网络（含基线检测）| Network (with baseline)
│       ├── gpu_monitor.py       # GPU
│       ├── system_monitor.py    # CPU/内存/磁盘 | CPU/Mem/Disk
│       ├── driver_monitor.py    # 设备驱动 | Device drivers
│       └── process_focus.py     # 进程焦点 | Process focus
├── tests/               # 测试（100 个用例）| Tests (100 cases)
├── docs/                # 文档 | Documentation
└── logs/                # 日志 | Logs
```

---

## 文档 | Docs

- [崩溃分析指南 | Crash Analysis Guide](docs/crash_analysis_guide.md) — 如何看懂崩溃报告和 Windows 事件日志
  How to read crash reports and Windows event logs

---

## License

MIT
