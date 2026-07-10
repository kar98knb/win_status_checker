# ETW 过滤验证实验

验证 `config.py` 中 `ETW_LEVEL` / `ETW_KEYWORD_BLACKLIST` / `ETW_EVENT_ID_WHITELIST` 三层过滤在真实异常场景下不影响诊断能力，同时把 IO 压到 SSD 能承受的水平。

## 方法论

对每个异常场景：

1. **同时启动两个 ETW session：**
   - `full`：全 keyword、Level=4、无 event id 过滤（对照组）
   - `filtered`：应用黑名单 + 白名单 + `ETW_LEVEL`（实验组）
2. **触发异常**
3. **停止 session，得到两份 .etl**
4. **对比分析**：实验组是否仍包含该异常的诊断事件

## 结论判定

- ✓ **过滤正确**：实验组和对照组都能识别出该异常
- ✗ **过滤过头**：只有对照组能识别 → 黑名单/白名单需调整

## 实验列表

| 脚本 | 场景 | 触发方式 |
|------|------|---------|
| `test_process_crash.py`      | 进程崩溃 vs 正常退出 | 三种子进程：exit(0) / raise / access violation |
| `test_disk_io_spike.py`      | 磁盘 IO 突发 | 大文件读写 + fsync |
| `test_cpu_saturation.py`     | CPU 占满 | 多进程忙循环打满所有核心 |
| `test_memory_pressure.py`    | 内存压力 | 分配到系统 ~70% 物理内存 |
| `test_network_disconnect.py` | 网络断开 | Disable/Enable-NetAdapter |

## 运行

### 1. 采集（需要管理员权限）

```
python tests/filter_validation/run_all.py
```

或单独跑一个：
```
python tests/filter_validation/test_process_crash.py
```

### 2. 分析（不需要管理员）

粗粒度：每个场景过滤前后的事件计数对比
```
python tests/filter_validation/analyze.py
```

进程崩溃细粒度：从 STOP 事件的 ExitStatus payload 识别真实崩溃
```
python tests/filter_validation/analyze_crash.py
```

## 输出

`tests/filter_validation/artifacts/<scenario>/`:
- `full.etl` — 全订阅
- `filtered.etl` — 三层过滤后
- `*.report.xml` / `*.summary.txt` — tracerpt 生成的统计（analyze.py 用）
- `*.events.xml` — tracerpt 生成的完整事件 payload（analyze_crash.py 用）

也可以手动用 WPA (Windows Performance Analyzer) 打开 `.etl` 查看。
