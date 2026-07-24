# Docker 与自定义路径安装

PersonaDock 支持三种安装方式：默认本地目录、自定义宿主机目录、运行中 Docker 容器内部目录。

## 1. 默认本地目录

```bash
personadock install ./persona.personapack --target hermes
personadock install ./persona.personapack --target openclaw
```

默认位置：

```text
Hermes:   ~/.hermes
OpenClaw: ~/.openclaw/workspace
```

## 2. 自定义宿主机目录

当 Hermes 或 OpenClaw 使用自定义数据目录，直接通过 `--path` 指定：

```bash
personadock install ./persona.personapack \
  --target hermes \
  --path /srv/hermes-data

personadock install ./persona.personapack \
  --target openclaw \
  --path /srv/openclaw/workspace
```

Windows 示例：

```powershell
personadock install .\persona.personapack `
  --target hermes `
  --path D:\AI\Hermes\data
```

## 3. Docker 绑定挂载

绑定挂载时优先写入宿主机目录，不需要进入容器，也不要求容器正在运行。

假设 Compose 配置为：

```yaml
services:
  hermes:
    volumes:
      - /srv/hermes-data:/root/.hermes
```

安装命令应使用宿主机路径：

```bash
personadock install ./persona.personapack \
  --target hermes \
  --path /srv/hermes-data
```

这是最稳定的 Docker 安装方式，因为容器重新创建后数据仍然保留。

## 4. Docker named volume 或容器内部目录

当数据只存在于 named volume 或容器文件系统中，使用 `--container`：

```bash
personadock install ./persona.personapack \
  --target hermes \
  --container hermes-app \
  --path /root/.hermes
```

OpenClaw 示例：

```bash
personadock install ./persona.personapack \
  --target openclaw \
  --container openclaw-app \
  --path /home/openclaw/.openclaw/workspace
```

不提供 `--path` 时，PersonaDock 会读取容器的 `$HOME` 并使用：

```text
Hermes:   $HOME/.hermes
OpenClaw: $HOME/.openclaw/workspace
```

容器模式要求：

- Docker CLI 可用
- 目标容器正在运行
- 容器内存在 POSIX `sh`
- 当前用户有权限执行 `docker exec` 和 `docker cp`

## 5. Docker Compose

建议使用稳定的 Compose 容器名称：

```bash
container="$(docker compose ps --format '{{.Name}}' hermes)"

personadock install ./persona.personapack \
  --target hermes \
  --container "$container" \
  --path /root/.hermes
```

不要优先使用短生命周期的容器 ID，因为回滚和卸载需要使用与安装记录一致的容器名称。

## 6. 回滚和卸载

宿主机自定义路径：

```bash
personadock rollback \
  --target hermes \
  --path /srv/hermes-data

personadock uninstall \
  --target hermes \
  --path /srv/hermes-data
```

Docker 容器：

```bash
personadock rollback \
  --target hermes \
  --container hermes-app \
  --path /root/.hermes

personadock uninstall \
  --target hermes \
  --container hermes-app \
  --path /root/.hermes
```

安装、回滚和卸载必须使用相同的 `--target`、`--container` 和 `--path`。

默认卸载会恢复安装前的文件。只删除 PersonaDock 管理的文件而不恢复旧版本：

```bash
personadock uninstall \
  --target hermes \
  --container hermes-app \
  --path /root/.hermes \
  --no-restore
```

## 7. 备份和状态

无论安装到本地还是容器，安装记录和旧文件备份都保存在宿主机：

```text
~/.personadock/state.json
~/.personadock/backups/
```

查看状态：

```bash
personadock status
```

容器安装会显示为：

```text
persona@0.1.0  hermes     docker://hermes-app/root/.hermes
```

## 8. 容器重建

推荐将 Hermes/OpenClaw 数据放在绑定挂载或 named volume 中。容器重建后：

- 绑定挂载：直接继续使用宿主机 `--path`
- named volume：使用挂载同一 volume 的新容器，并保持稳定容器名称
- 纯容器文件系统：容器删除后数据和 PersonaDock 安装都会丢失
