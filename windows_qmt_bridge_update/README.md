# Windows QMT Bridge 更新说明

## 是否需要修正 Windows 文件

需要。当前 Mac 项目里的后端已经按“三仓隔离”调整完成，但 Windows 机器上运行的 QMT Bridge 也必须替换成最新版本，否则可能仍然只有模拟盘桥接，或无法启动实盘仓桥接。

## 需要复制到 Windows 的文件

把本目录下所有文件复制到 Windows：

- 源目录：`windows_qmt_bridge_update/`
- 目标目录：`D:\QMT\`

复制后 Windows 目录应为：

- `D:\QMT\start_qmt_bridge.bat`
- `D:\QMT\start_qmt_bridge.ps1`
- `D:\QMT\start_qmt_bridge_live.bat`
- `D:\QMT\start_qmt_bridge_live.ps1`
- `D:\QMT\scripts\qmt_bridge_server.py`

## 启动方式

### 模拟盘

1. 登录模拟 QMT。
2. 双击 `D:\QMT\start_qmt_bridge.bat`。
3. 默认监听端口：`8710`。
4. 对应账户：`39027628`。
5. 对应页面：虚拟仓。

### 实盘

1. 登录实盘 QMT。
2. 双击 `D:\QMT\start_qmt_bridge_live.bat`。
3. 默认监听端口：`8711`。
4. 对应账户：`8886186680`。
5. 对应页面：实盘仓。

## 三仓隔离关系

- 虚拟仓：只读取模拟盘 QMT，不写入跟踪看板。
- 实盘仓：只读取实盘 QMT，不写入跟踪看板。
- 跟踪看板：保持原有独立逻辑，不读取模拟盘/实盘 QMT 仓位。

## 连通性验证

在 Mac 项目机器上验证：

```bash
curl -sS -H "Authorization: Bearer your-bridge-token" http://192.168.10.1:8710/health
curl -sS -H "Authorization: Bearer your-bridge-token" http://192.168.10.1:8711/health
```

如果 `8711` 返回连接失败，说明实盘 Bridge 还没启动，或 Windows 防火墙没有放行端口。
