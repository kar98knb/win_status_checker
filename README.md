# win_status_checker

用 ETW (Event Tracing for Windows) 事后重建游戏卡顿现场的诊断工具。产物是合法 `.etl` 文件，**WPA 直接双击可打开**。

A Windows post-mortem diagnostic tool that uses ETW to reconstruct game stuttering incidents. Output is native `.etl` — open directly in **Windows Performance Analyzer (WPA)**.

---

## 架构 | Architecture

双 ETW session 组合，覆盖不同的故障场景：

Two ETW sessions cover different failure modes:

| Session | 类型 Mode | 作用 Purpose |
|---|---|---|
| **File Session** | File Circular（磁盘）| 只订阅"崩溃/断连"这种确凿的低频事件，长期落盘。**目的**：蓝屏/hang 后重启也能从盘上找到"最后发生了什么" |
| **Buffer Session** | Buffering（纯内存环形）| 广撒网订阅高频事件，事件只在内核内存 buffer 里循环。**零磁盘 IO**。Ctrl+C 时 `ControlTraceW(FLUSH)` 一次性写成 `.etl`。**目的**：用户感知卡顿时立即 Ctrl+C，抓最近几分钟历史 |

### Data flow

```
Kernel providers                                    Kernel providers
     ↓                                                    ↓
[File Session]                                    [Buffer Session]
  Kernel-Process (1/2/3/5/6/10)                     CPU-Power
  DxgKrnl (TDR 540/541/547/548)                     Kernel-Power
  Kernel-PnP (39 event id)                          Kernel-Disk
  Kernel-Memory (MEMINFO)                           USB / BTH / HID / Audio
  TCPIP (64 event id)                                    ↓
     ↓                                              内核环形 buffer (默认 256 MB)
  60s flush                                              ↓
     ↓                                              Ctrl+C: ControlTraceW(FLUSH)
                                                          ↓
[logs/runs/<ts>/keyevents.etl]                     [logs/runs/<ts>/snap.etl]
   ~5 MB/min（无感 IO）                                ~几十 MB，一次性写盘
                                                     WPA 直接可开
```

**关键：Buffer Session 平时零磁盘 IO**，只在 Ctrl+C 一次性写盘。产物直接是原生 ETL 格式，用 WPA / tracerpt / xperf 分析，不需要额外解析器。

---

## 系统要求 | Requirements

- Windows 10 / 11（其他 Windows 未测试）
- Python 3.10+
- **管理员权限**（ETW kernel provider 订阅要求）
- 分析工具：[Windows Performance Analyzer (WPA)](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/windows-performance-analyzer)（或 `tracerpt.exe`）

---

## 快速开始 | Quick Start

```
python install.py                     # 安装 tinycc 依赖（一次性，测试用）
python run.py                         # 管理员 shell 启动监控
                                      # Ctrl+C 停止并 flush 内存 buffer 到 snap.etl
```

每次运行的产物在 `logs/runs/<YYYYMMDD_HHMMSS>/`:

```
logs/runs/20260714_162021/
├── main.log            # 运行日志（stdout + stderr + logging 全汇总）
├── keyevents.etl       # File Session 关键事件流水（可在监控中查看历史）
└── snap.etl            # Buffer Session Ctrl+C 时的内存快照（合法 ETL）
```

用 WPA 打开：

```
wpa.exe logs\runs\<ts>\snap.etl
wpa.exe logs\runs\<ts>\keyevents.etl
```

---

## 测试 | Tests

统一测试入口：

```
python run.py --test
```

入口会自动检查权限：

- **普通权限**：运行全部无权限单元测试，覆盖 GUID、过滤配置、ctypes 内存布局、Event ID 白名单指针链及配置自洽性；并明确提示已跳过 ETW 集成测试。
- **管理员权限**：在单元测试基础上，追加真实的 File + Buffer 双 Session、FLUSH 生成 ETL、`tracerpt` 可读性集成测试。

CPU 满载、内存压力、磁盘压力和断网属于有明显副作用的人工故障实验，`--test` 不会自动触发。它们仍位于 `tests/filter_validation/test_*.py`；`tests/io_estimate.py` 也保留为人工 IO 评估工具。`analyze.py` 和 `analyze_crash.py` 只分析已有 ETL，不需要管理员权限。

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
│   ├── logging_utils.py            # stdout tee 到文件
│   ├── compat/                     # Windows 控制台 UTF-8 适配
│   └── etw/                        # 纯 ctypes 实现的 ETW 采集层
│       ├── providers.py            #   provider GUID 定义
│       ├── session.py              #   两种 session (File Circular / Buffering)
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

Buffer Session 广撒网，不用 event id 白名单——事件在内存里，白名单错杀反而丢诊断信号。

---

## 依赖 | Dependencies

**运行时零依赖**——ctypes 直接调 Windows API，没有 psutil / wmi / pywin32。

Only test dependency: `tinycc` (used by `tests/filter_validation/test_process_crash.py`
to compile a native crash.c that triggers a real access violation).

---

## License

MIT
