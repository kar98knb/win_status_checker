# win_status_checker

用 ETW (Event Tracing for Windows) 事后重建游戏卡顿现场的诊断工具。

A Windows post-mortem diagnostic tool that uses ETW to reconstruct game stuttering incidents.

---

## 架构 | Architecture

双 session 组合，覆盖不同的故障场景：

Two ETW sessions cover different failure modes:

| Session | 类型 Mode | 作用 Purpose |
|---|---|---|
| **File Session** | File Circular（磁盘）| 只订阅"崩溃/断连"这种确凿的低频事件，长期落盘。**目的**：蓝屏/hang 后重启也能从盘上找到"最后发生了什么" |
| **Realtime Session** | Real-Time Consumer（内存）| 广撒网订阅高频事件，事件走 kernel → 用户态 → Python deque，**零磁盘 IO**。**目的**：用户感知卡顿时立即 Ctrl+C，抓最近几分钟历史 |

### Data flow

```
Kernel providers                                    Kernel providers
     ↓                                                    ↓
[File Session]                                    [Realtime Session]
  Kernel-Process (1/2/3/5/6/10)                     CPU-Power
  DxgKrnl (TDR 540/541/547/548)                     Kernel-Power
  Kernel-PnP (39 event id)                          Kernel-Disk
  Kernel-Memory (MEMINFO)                           USB / BTH / HID / Audio
  TCPIP (64 event id)                                    ↓
     ↓                                              ProcessTrace callback
  60s flush                                              ↓
     ↓                                              deque(maxlen=1M)
[logs/runs/<ts>/keyevents.etl]                     [logs/runs/<ts>/snap.bin.gz]
   ~5 MB/min（无感 IO）                                Ctrl+C 时 dump ~10 MB
```

---

## 系统要求 | Requirements

- Windows 10 / 11（其他 Windows 未测试）
- Python 3.10+
- **管理员权限**（ETW kernel provider 订阅要求）

---

## 快速开始 | Quick Start

```
python install.py                     # 安装 tinycc 依赖（一次性，测试用）
python run.py                         # 管理员 shell 启动监控
                                      # Ctrl+C 停止并 dump snapshot

python -m src.analyze_snapshot        # 分析最新 snapshot（不需要管理员）
python -m src.analyze_snapshot --list # 列出所有历史 run
```

每次运行的产物在 `logs/runs/<YYYYMMDD_HHMMSS>/`:

```
logs/runs/20260714_162021/
├── main.log            # 运行日志（stdout + stderr + logging 全汇总）
├── keyevents.etl       # File Session 关键事件（tracerpt 或 WPA 可打开）
└── snap.bin.gz         # Realtime Session Ctrl+C 时的内存 dump
```

---

## 项目结构 | Project Structure

```
win_status_checker/
├── run.py                          # 入口
├── install.py                      # venv + 依赖安装
├── config/
│   └── config.py                   # ETW 过滤配置（provider / event id 白名单）
├── src/
│   ├── main.py                     # 双 session 主循环
│   ├── analyze_snapshot.py         # snapshot 离线分析
│   ├── logging_utils.py            # stdout tee 到文件
│   ├── compat/                     # Windows 控制台 UTF-8 适配
│   └── etw/                        # 纯 ctypes 实现的 ETW 采集层
│       ├── providers.py            #   provider GUID 定义
│       ├── session.py              #   3 种 session (File / Realtime / Buffering)
│       ├── consumer.py             #   Real-Time Consumer + 内存 deque + gzip dump
│       └── provider_registry.py    #   provider name → filter 配置解析
├── tests/
│   ├── io_estimate.py              # 评估订阅新 provider 的 IO 代价
│   └── filter_validation/          # 5 个故障场景 + 白名单验证
└── logs/runs/<ts>/                 # 每次运行的产物目录
```

---

## Event ID 白名单是怎么来的 | How the whitelist was built

`config/config.py` 里 `ETW_EVENT_ID_WHITELIST` 每个 event id 都能讲一个 story。
来源：`tests/filter_validation/` 里 6 个故障场景各跑一次，从 filtered.etl 里
统计每个 (provider, event id) 在哪个场景显著出现。

- 只在某场景高发的 event id → 该场景的核心信号，进白名单
- 每个场景都均匀出现的 event id → 背景噪音，剔除

5 个 provider（DxgKrnl / Kernel-Process / Kernel-PnP / Kernel-Memory / TCPIP）
共 119 个 event id 进 File Session 白名单，每个都带注释说明"看到这个说明系统里发生了什么"。

---

## 依赖 | Dependencies

**运行时零依赖**——ctypes 直接调 Windows API，没有 psutil / wmi / pywin32。

Only test dependency: `tinycc` (used by `tests/filter_validation/test_process_crash.py`
to compile a native crash.c that triggers a real access violation).

---

## License

MIT
