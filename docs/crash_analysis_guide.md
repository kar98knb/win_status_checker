# 崩溃分析指南 | Crash Analysis Guide

本文档帮助你理解 win_status_checker 给出的崩溃报告，以及如何利用 Windows 系统事件判断问题原因。

---

## 1. 重启后你会看到什么

当监控工具检测到上次异常退出时，会输出类似这样的信息：

```
⚠ 检测到上次异常退出！
  卡死前各项指标正常，可能是游戏本身或显卡驱动问题
  详细报告: logs/crash_report.json

⚠ 事件日志发现 GPU 驱动崩溃(TDR)记录！

ℹ 过去24h有 3 条系统异常事件（详见日志）
```

这些信息来自三个来源：
- **快照** (`last_snapshot.json`) — 卡死前 2 秒的系统状态
- **Windows 事件日志** — 系统自动记录的崩溃/异常事件
- **崩溃转储文件** — Windows 在崩溃时保存的内存 dump

---

## 2. 常见场景和判断方法

### 场景 A：GPU 驱动崩溃

**表现**：画面冻住、屏幕黑一下又恢复，或直接卡死

**在本工具中的信号**：
- 事件日志：`Event 4101 (Display)` — "显示设备驱动程序停止响应并已恢复"
- 事件日志：`Event 1000 (Application Error)` — 故障模块为 GPU 驱动文件
- 快照：GPU 使用率/显存可能接近满载

**GPU 驱动文件名对照**：
| 文件名 | 对应显卡 |
|--------|---------|
| `nvlddmkm.sys` | NVIDIA |
| `ig9icd64.dll` / `igdkmd64.sys` | Intel |
| `amdkmdap` / `atikmpag.sys` | AMD |

**建议**：更新显卡驱动，或回退到上一个稳定版本

---

### 场景 B：系统 hang 后强制断电

**表现**：整个系统无响应（鼠标不动、音频卡住），只能长按电源

**在本工具中的信号**：
- 事件日志：`Event 41 (Kernel-Power)` — "系统在未先正常关机的情况下重新启动"
- 事件日志：`Event 6008 (EventLog)` — "上一次系统关机是意外的"
- 快照存在且时间戳过期 → 异常退出确认

**需要结合快照判断原因**：
| 快照中的线索 | 可能原因 |
|-------------|---------|
| GPU 温度 > 90°C | 显卡过热导致 hang |
| 内存使用 > 95% | 内存耗尽，系统换页卡死 |
| CPU 降频 + 高负载 | CPU 过热降频到极低频率 |
| 一切正常 | 可能是驱动死锁或硬件问题 |

---

### 场景 C：蓝屏 (BSOD)

**表现**：突然蓝屏，显示错误代码后自动重启

**在本工具中的信号**：
- 崩溃转储：`C:\Windows\Minidump\` 目录出现新的 `.dmp` 文件
- 事件日志：`Event 41 (Kernel-Power)`

**常见蓝屏代码**：
| 代码 | 含义 | 常见原因 |
|------|------|---------|
| `VIDEO_TDR_FAILURE` | 显卡驱动超时 | GPU 驱动 bug 或过热 |
| `IRQL_NOT_LESS_OR_EQUAL` | 驱动访问非法内存 | 驱动冲突（反作弊常见） |
| `PAGE_FAULT_IN_NONPAGED_AREA` | 内存错误 | 内存条故障或驱动 bug |
| `KERNEL_MODE_HEAP_CORRUPTION` | 内核堆损坏 | 驱动 bug |
| `SYSTEM_SERVICE_EXCEPTION` | 系统服务异常 | 反作弊驱动冲突 |

**建议**：用 WinDbg 打开 `.dmp` 文件可以看到具体崩溃栈

---

### 场景 D：游戏自己崩溃（系统没事）

**表现**：游戏突然关闭，桌面正常

**在本工具中的信号**：
- 焦点进程退出记录：`[焦点进程退出] XXGame.exe 已退出/崩溃`
- 事件日志：`Event 1000 (Application Error)` — 记录崩溃的程序名和异常代码
- 无 Event 41（系统没有重启）

**Event 1000 里的关键信息**：
```
故障应用程序名称:  XXGame.exe
故障模块名称:      XXGame.dll    ← 如果是游戏自己的模块 = 游戏 bug
                   ntdll.dll     ← 系统库，通常是内存问题
                   nvlddmkm.sys ← 显卡驱动触发的崩溃
异常代码:          0xc0000005    ← ACCESS_VIOLATION，内存越界
```

---

### 场景 E：网络问题导致掉线

**表现**：游戏突然掉线或卡顿

**在本工具中的信号**：
- 快照：`network.is_connected = false` 或 `packet_loss_percent` 突增
- 快照：`network.link_down_count` 增加（链路闪断）
- 快照：`network.nic_errors_delta > 0`（物理层错误，可能网线接触不良）
- 快照：`network.jitter_ms` 很高（网络不稳定）

**网线接触不良的典型表现**：
- `link_down_count` 不断增加
- `nic_errors_delta` 有非零值
- 延迟和丢包偶尔突增

---

## 3. 如何手动查看 Windows 事件日志

如果你想自己去看更多细节：

1. 按 `Win + R`，输入 `eventvwr.msc`，回车
2. 左侧导航：`Windows 日志` → `系统` 或 `应用程序`
3. 右侧点 `筛选当前日志`，输入事件 ID（如 41, 4101, 1000）

或者用 PowerShell 快速查询：

```powershell
# 查看最近的意外关机事件
Get-WinEvent -FilterHashtable @{LogName='System'; ID=41} -MaxEvents 5

# 查看 GPU TDR 事件
Get-WinEvent -FilterHashtable @{LogName='System'; ID=4101} -MaxEvents 5

# 查看应用崩溃
Get-WinEvent -FilterHashtable @{LogName='Application'; ID=1000} -MaxEvents 5
```

---

## 4. 本工具关注的事件 ID 汇总

| 日志源 | Event ID | 名称 | 含义 |
|--------|----------|------|------|
| System | 41 | Kernel-Power | 意外断电/卡死后重启 |
| System | 6008 | EventLog | 上一次关机异常 |
| System | 4101 | Display | GPU 驱动超时恢复 (TDR) |
| System | 14 | nvlddmkm | NVIDIA 驱动错误 |
| System | 7034 | SCM | Windows 服务意外停止 |
| Application | 1000 | Application Error | 应用程序崩溃（含模块名、异常代码） |
| Application | 1001 | WER | Windows 错误报告详情 |

---

## 5. crash_report.json 字段说明

重启后工具生成的 `logs/crash_report.json` 结构：

```json
{
  "detected_at": 1717000000,
  "last_snapshot_time": 1716999990,
  "gap_seconds": 7200,
  "last_state": {
    "network": { "is_connected": true, "latency_ms": 25 },
    "gpu": { "gpu_usage_percent": 95, "temperature_celsius": 88 },
    "system": { "memory_percent": 92, "cpu_throttled": false },
    "process_focus": { "focused": { "name": "XXGame.exe", "cpu_percent": 70 } }
  },
  "conclusion": "可能原因: GPU 过热 (88°C)，可能导致显卡驱动崩溃"
}
```

| 字段 | 含义 |
|------|------|
| `gap_seconds` | 快照到重启之间过了多久（越大说明 hang 越久或关机越久） |
| `last_state` | 卡死前最后一次完整采集的系统状态 |
| `conclusion` | 工具基于阈值自动推测的原因 |
| `process_focus.focused` | 卡死时正在追踪的高占用进程（通常是游戏） |

---

## 6. 拿到这些信息后该怎么办

| 结论 | 行动 |
|------|------|
| GPU 驱动崩溃 | 更新/回退显卡驱动，降低游戏画质 |
| GPU 过热 | 清灰、检查散热、降低功耗限制 |
| 内存耗尽 | 关闭后台程序、加内存条 |
| CPU 降频 | 检查散热、清灰、使用散热底座 |
| 网线接触不良 | 换网线、重新插拔、换网口 |
| 游戏自身 bug | 验证游戏文件完整性、等更新 |
| 反作弊冲突 | 关闭冲突软件（虚拟机、调试器等） |
| 指标全正常 | 可能是偶发驱动死锁，观察是否复现 |
