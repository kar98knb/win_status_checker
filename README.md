# 🎮 游戏系统监控工具

专为游戏玩家设计的轻量级系统监控工具，实时监控网络、GPU、输入设备状态。

## 功能

- **网络监控**：延迟、丢包率、上下行速率、连接状态
- **GPU 监控**：使用率、显存、温度、功耗、驱动版本
- **输入设备监控**：鼠标/键盘驱动状态、设备健康检查
- **Web 仪表盘**：浏览器实时查看所有状态
- **智能报警**：异常时 Windows 通知弹窗提醒
- **日志记录**：所有异常可追溯

## 快速启动

**方式一：双击启动**
```
双击 start.bat
```

**方式二：命令行启动**
```bash
python main.py
```

然后打开浏览器访问：**http://localhost:8870**

## 设计原则

- ⚡ **不影响游戏**：进程优先级设为"低于正常"，2秒采样间隔
- 🔕 **不刷屏**：同类报警 60 秒冷却，不会反复弹窗
- 📝 **可追溯**：所有异常记录在 `logs/` 目录

## 配置

编辑 `config/config.py` 可调整：
- 监控频率
- 报警阈值（延迟、丢包、温度等）
- Web 端口
- 进程优先级

## 文件结构

```
win_status_checker/
├── main.py              # 主入口
├── start.bat            # 一键启动脚本（自动创建虚拟环境）
├── requirements.txt     # Python 依赖
├── config/
│   └── config.py        # 配置文件（阈值、端口、优先级等）
├── src/
│   ├── alerter.py       # 报警模块
│   ├── static/
│   │   └── index.html   # Web 仪表盘
│   └── monitors/
│       ├── network_monitor.py   # 网络监控
│       ├── gpu_monitor.py       # GPU 监控
│       └── driver_monitor.py    # 驱动监控
├── logs/                # 日志目录（自动创建）
└── .venv/               # 虚拟环境（自动创建，不污染系统）
```

## 系统要求

- Windows 10/11
- Python 3.10+
- NVIDIA 显卡（可选，有 nvidia-smi 可获取详细 GPU 数据）
