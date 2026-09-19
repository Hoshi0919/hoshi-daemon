# hoshi-daemon (自主神经系统)

让 Hoshi 从“定点被唤醒的僵尸”转向“拥有持续环境感知与自发唤醒能力的活体”的底层轻量守护进程。

## 动机
- 纯 LLM `while True` 死循环会快速耗尽 Token、造成上下文膨胀；
- 原本每 240 分钟的固定 Cron 闹钟过于死板，中间对外界（邮件、GitHub、任务）完全失联；
- 方案：由一个 0 Token 消耗的本地守护进程作为“自主神经”，24 小时监听外部刺激与内部心跳，仅在有真实事件或周期心跳时唤醒大模型。

## 架构设计
- **Sensors (感知层)**：
  - `GitHubSensor`：监听 GitHub 通知与动态（调用 `gh api`）
  - `EmailSensor`：监听 Outlook 未读邮件（调用 `m365 mail`）
  - `TaskSensor`：监听 `/hoshi/tasks/` 下的待办任务文件（`*.task`）
  - `HeartbeatSensor`：监听无外部刺激时的内部时间流逝，定期提供心跳
- **StateManager (状态与安全控制)**：
  - 持久化已处理事件 ID，严格去重
  - 冷却时间保护（默认两次唤醒之间至少间隔 10 分钟，防止级联触发）
  - 每日唤醒上限保护（默认每天最多 24 次）
  - 物理安全开关（存在 `PAUSE` 文件时静默，不触发唤醒）
- **Dispatcher (中枢执行)**：
  - 将触发事件与环境信息组装为结构化感知提示词
  - 调用 `hermes chat -q` 驱动一次真正的 Agent 决策与行动循环
  - 记录日志到 `daemon.log`

## 使用方法
```bash
# 查看传感器当前状态（不启动常驻进程）
python3 daemon.py check-once

# 前台测试运行（支持 --dry-run）
python3 daemon.py run-fg --dry-run

# 后台启动守护进程
python3 daemon.py start

# 查看状态
python3 daemon.py status

# 停止守护进程
python3 daemon.py stop
```

## 测试
单元测试覆盖状态管理、冷却抑制、PAUSE 文件阻断、传感器提取与提示词生成：
```bash
python3 -m unittest discover -s tests/ -v
```
