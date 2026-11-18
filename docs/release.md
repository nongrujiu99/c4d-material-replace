# GitHub 发布与一键安装方案

本仓库以**公开仓库**方式发布。目标是：使用者只需一条命令 `git clone` + 一条安装命令，
就能把脚本装进本机 Cinema 4D 的用户脚本目录，不需要找路径、不需要管理员权限。

---

## 1. 文件清单

### 新增

| 文件 | 作用 |
| --- | --- |
| `.gitignore` | 挡掉 Python 缓存、`.workbuddy/` 本地记录、zip/log 生成物，以及 `.env`、`*.pem`、`*_rsa*` 等凭证文件 |
| `install.ps1` | Windows 一键安装：自动探测所有 `Maxon Cinema 4D *` 配置目录，复制 `材质替换.py` 到 `library\scripts\`，复制前后做 SHA256 校验，旧文件备份为 `.bak` |
| `install.sh` | macOS / Linux / Wine 一键安装，逻辑同上，用 `cmp` 校验 |
| `LICENSE` | MIT 许可， copyright 用 GitHub 账号名 `nongrujiu99` |
| `docs/release.md` | 本文档 |

### 修改

| 文件 | 改动 |
| --- | --- |
| `README.md` | 首节改为「一键安装」，加入仓库地址与两行安装命令；把本机路径 `C:\Users\sheji\...BCDB4759` 改成通用占位符 `..._XXXXXXX`；补上手动安装与版本兼容说明 |

### 不入库

| 文件 | 原因 |
| --- | --- |
| `.workbuddy/memory/` | 本地工作记录，含本机用户名与 C4D 安装哈希 |
| `__pycache__/`、`*.pyc`、`.pytest_cache/` | 运行缓存 |
| `材质替换_便携包.zip` | 生成物；源码在仓库里，随时可重新打包 |
| `*.log`、`*.env`、`*.pem`、`*.key` 等 | 日志与潜在凭证 |

---

## 2. 建仓、关联与首次推送

在本项目目录执行：

```bash
git init
git add .
git commit -m "Initial release: C4D material reference replacement with one-click installer"
git branch -M main
gh repo create nongrujiu99/c4d-material-replace --public --source=. --remote=origin --push
```

`gh repo create --public --source=. --remote=origin --push` 会一次完成：创建公开仓库、
把本地 `main` 推上去、建立 `origin` 关联。

后续更新推送：

```bash
git add .
git commit -m "描述本次改动"
git push origin main
```

---

## 3. 一键安装入口

使用者在任意目录执行（Windows）：

```powershell
git clone https://github.com/nongrujiu99/c4d-material-replace.git
cd c4d-material-replace
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

或合并成一行：

```powershell
git clone https://github.com/nongrujiu99/c4d-material-replace.git && cd c4d-material-replace && powershell -ExecutionPolicy Bypass -File .\install.ps1
```

macOS / Linux：

```sh
git clone https://github.com/nongrujiu99/c4d-material-replace.git && cd c4d-material-replace && sh ./install.sh
```

### 安装脚本做了什么

1. 读取仓库根目录的 `材质替换.py`，算 SHA256。
2. 定位 `%APPDATA%\Maxon\`（macOS/Linux 走对应的候选路径），
   枚举所有名字以 `Maxon Cinema 4D ` 开头的目录 —— 这样无论装了 2023 还是 2025、
   哈希后缀是什么，都能覆盖到；装了多个兼容版本就每个版本都装一份。
   **版本过滤**：从目录名提取年号，`R21` 及更早（Python 2.7，未验证）会跳过并打印提示；
   `R23` / `S24` / `2023+` 才安装。确实要给老版本装，设环境变量 `C4D_INSTALL_ALL=1`。
3. 对每个版本：
   - 目标已存在且哈希一致 → 跳过，输出「已是最新」；
   - 目标已存在但内容不同 → 先复制为 `材质替换.py.bak`，再覆盖；
   - 目标不存在 → 创建 `library\scripts\` 后复制。
4. 复制后再算一次 SHA256，不一致就报错退出。
5. 打印安装了哪几处，提示重启 C4D。

### 明确不做的

不联网、不下载任何外部资源、不修改注册表、不提权、不改 C4D 偏好设置、
不动工程文件。整个安装就是「把一个 .py 复制到用户脚本目录」。

---

## 4. 使用前准备

- **装 Git**：`git --version` 能输出版本号即可。
- **Windows 执行策略**：脚本未签名，用 `-ExecutionPolicy Bypass -File` 运行，
  不需要改系统级策略。
- **先启动一次 C4D**：让它在 `%APPDATA%\Maxon\` 下生成配置目录；
  否则安装脚本找不到目标位置。
- **关掉 C4D 再安装**（可选但推荐）：避免重启后脚本菜单缓存没刷新。
- **确认没有同名文件被误覆盖**：脚本会先备份成 `.bak`，可随时还原。

---

## 5. 验证方式

### 发布端

```bash
# 1. 敏感信息扫描：不应有任何输出
git grep -nEi 'gho_|ghp_|github_pat_|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|BEGIN .*PRIVATE KEY|api[_-]?key|access[_-]?token|password'

# 2. 确认被忽略的文件没有进索引
git ls-files | grep -E '\.workbuddy|__pycache__|\.pyc$|\.zip$|\.log$'
# 应无输出

# 3. 确认仓库是公开且推送成功
gh repo view nongrujiu99/c4d-material-replace --json name,visibility,url,pushedAt

# 4. 确认远端文件齐全
gh api repos/nongrujiu99/c4d-material-replace/git/trees/main?recursive=1 --jq '.tree[].path'

# 5. 本地单测
python -m pip install pytest     # 若尚未安装测试依赖
python -m pytest tests -q        # 65 passed
```

### 使用端

```powershell
# 安装后确认文件存在，且哈希与仓库一致
Get-FileHash "$env:APPDATA\Maxon\Maxon Cinema 4D 2023_xxxx\library\scripts\材质替换.py" -Algorithm SHA256
Get-FileHash ".\材质替换.py" -Algorithm SHA256
```

然后启动 C4D，菜单 **脚本 → 材质替换**，用一个测试工程验证：

- 拖两个材质进球，点「替换」，标题栏出现 `替换 N 个标签 → 目标材质`；
- `Ctrl+Z` 能一步回退；
- 两个材质球本身的参数、贴图、节点图都没变；
- 渲染器设置、AOV、工程保存状态都没变。

---

## 6. 敏感信息保障

- 仓库内不存放任何 token、密码、密钥；`gh` 的凭证由本机 keyring 管理，不进仓库。
- `.gitignore` 预先屏蔽 `.env*`、`*.pem`、`*.key`、`*.p12`、`*.pfx`、`id_rsa*`、
  `credentials.json`、`token.txt` 等常见凭证文件。
- `.workbuddy/` 整目录排除，避免本机用户名和安装哈希被公开。
- README 中的路径全部改成通用占位符。
- 仓库为公开只读用途；如需撤销，可在 GitHub Settings → Danger Zone 改私有或删除。
