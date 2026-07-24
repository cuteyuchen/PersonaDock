# PersonaPack 信任与私有加密备份

PersonaPack 公共分发和 Persona 私有备份是两种不同产物：

- PersonaPack：可部署、默认不含私有原始资料和运行时状态。
- Private Backup：加密保存完整 Persona 工程，包括 `.private/`，用于用户自己恢复。

## PersonaPack 完整性

```bash
personadock trust verify ./xiaoyou.personapack --json
```

未签名包可以验证：

- Manifest 格式与兼容范围。
- 每个已声明文件的 SHA-256。
- 是否出现未声明的额外文件。
- Canonical Schema 和 Adapter API 是否受当前版本支持。

这只能证明归档内部自洽，不能证明发布者身份。

## 生成 Ed25519 签名密钥

```bash
personadock trust keygen ~/.config/personadock/signing.pem
```

生成：

```text
signing.pem
signing.pem.pub
```

私钥文件会尽可能设置为仅当前用户可读写。不要把私钥提交到 Git、PersonaPack 或公开附件。

## 签名

```bash
personadock trust sign ./xiaoyou.personapack \
  --key ~/.config/personadock/signing.pem
```

默认生成：

```text
xiaoyou.personapack.sig.json
```

签名是分离式 Ed25519 签名，覆盖完整 PersonaPack 字节，包括 ZIP 容器和 Manifest。

## 按可信 Key 验证

```bash
personadock trust verify ./xiaoyou.personapack \
  --signature ./xiaoyou.personapack.sig.json \
  --trusted-key ~/.config/personadock/signing.pem.pub \
  --json
```

结果：

- `valid-trusted`：签名有效，Key ID 在显式可信列表中。
- `valid-untrusted-key`：签名有效，但 Key 未被用户显式信任。
- `unsigned`：没有提供签名。
- `invalid`：归档、摘要、签名或公钥不匹配。

PersonaDock 不自动信任签名中自带的公钥。

## 创建私有备份

优先通过环境变量提供密码，避免出现在 Shell History 或进程参数中：

```bash
export PERSONADOCK_BACKUP_PASSWORD='use-a-long-unique-password'
personadock backup create ./xiaoyou \
  --output ./xiaoyou-private.pdbackup
```

Windows PowerShell：

```powershell
$env:PERSONADOCK_BACKUP_PASSWORD = "use-a-long-unique-password"
personadock backup create .\xiaoyou `
  --output .\xiaoyou-private.pdbackup
```

未设置环境变量且终端可交互时，CLI 会隐藏输入密码。

## 加密格式

Private Backup v1 使用：

- ZIP 封装 Persona 工程文件。
- Scrypt 密钥派生。
- AES-256-GCM 认证加密。
- 随机 Salt 和 Nonce。
- Header 作为认证附加数据。
- 解密后再次验证归档 SHA-256。

修改密文、Header 或使用错误密码都会导致认证失败，不会输出部分恢复文件。

## 备份范围

包含：

- `companion.yaml`
- Skills 和 References
- 已审核 Memory
- `.private/` 中的原始资料、证据和候选
- Tests 和本地设计记录

排除：

- `.git`、`.hg`、`.svn`
- Cache 和 `__pycache__`
- `dist/`
- `.personadock/build/`
- Hermes/OpenClaw 认证、OAuth Token、Sessions、Transcript 和 State

Private Backup 只读取 Persona 工程目录，不扫描运行时主目录。

## 检查 Header

不需要密码即可查看非敏感 Header：

```bash
personadock backup inspect ./xiaoyou-private.pdbackup --json
```

Header 包含 Persona ID/版本、算法、创建时间、文件数量和归档摘要，不包含明文人格内容。

## 恢复

```bash
export PERSONADOCK_BACKUP_PASSWORD='use-a-long-unique-password'
personadock backup restore ./xiaoyou-private.pdbackup ./xiaoyou-restored
```

目标目录非空时默认停止。确认覆盖：

```bash
personadock backup restore ./xiaoyou-private.pdbackup ./xiaoyou-restored --force
```

恢复后执行：

```bash
personadock validate ./xiaoyou-restored
personadock test ./xiaoyou-restored
personadock diff ./xiaoyou ./xiaoyou-restored
```

## 密钥与备份建议

- 签名私钥和备份密码分开保存。
- Public Key 可以公开，Private Key 不公开。
- 私有备份至少保留两个离线副本。
- 定期做恢复演练，而不只检查文件存在。
- 删除 Persona 前先创建私有备份和平台原生快照。
