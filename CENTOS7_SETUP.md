# CentOS 7 上的 Hermes MCP 安裝與啟動

這份指南適用於：

- CentOS Linux 7
- `python3 -V` 顯示 `3.6.8` 或其他較舊版本
- 想保留系統 Python，不覆蓋 `/usr/bin/python3`

## 建議策略

不要直接改系統 Python。  
建議做法是：

1. 將 CentOS 7 套件來源切到 vault
2. 安裝 `rh-python38`
3. 用 `scl enable rh-python38` 或 `venv` 跑 Hermes

Red Hat Software Collections 會把新版 Python 安裝在 `/opt/`，不會替換系統工具。

## 1. 檢查現況

```bash
cat /etc/os-release
python3 -V
which python3
```

如果你看到：

- `CentOS Linux 7`
- `Python 3.6.8`

就可以照下面步驟做。

## 2. 切換 CentOS 7 repo 到 vault

CentOS 7 已經 EOL，建議改用 vault。

```bash
sudo sed -i.bak \
  -e 's/^mirrorlist=/#mirrorlist=/g' \
  -e 's|^#baseurl=http://mirror.centos.org|baseurl=http://vault.centos.org|g' \
  /etc/yum.repos.d/CentOS-Base.repo

sudo yum clean all
sudo yum makecache
```

## 3. 安裝新版 Python

安裝 Software Collections 與 Python 3.8：

```bash
sudo yum install -y centos-release-scl
sudo yum install -y rh-python38 rh-python38-python-pip rh-python38-python-devel
```

## 4. 啟用 Python 3.8

開一個新的 shell session：

```bash
scl enable rh-python38 bash
python3 -V
```

你應該會看到 `Python 3.8.x`。

## 5. 建立虛擬環境

建議讓 Hermes 跑在 venv 裡面：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -V
python -m pip install -U pip setuptools wheel
```

## 6. 啟動 Hermes

在專案目錄中執行：

```bash
python hermes_mcp_server.py
```

如果你不想進入 venv，也可以直接用：

```bash
scl enable rh-python38 'python3 hermes_mcp_server.py'
```

## 7. 常用測試

檢查治理工具：

```bash
python hermes_mcp_governance.py improvements
python hermes_mcp_governance.py check --tool obsidian_create_note --path /data/obsidian-vault/APISIX/JWT-Auth.md
python hermes_mcp_governance.py check --commit-message "[Hermes] Create APISIX JWT Guide"
```

## 8. 問題排查

### 找不到 `rh-python38`

先確認 vault 與 SCL repo 是否可用：

```bash
sudo yum repolist
sudo yum search rh-python38
```

### `python3` 還是舊版

請確認你有先啟用 SCL：

```bash
scl enable rh-python38 bash
python3 -V
```

### 想永遠使用新版 Python

不要修改系統 `/usr/bin/python3`。  
建議改成：

- 用 shell alias
- 用 venv
- 用 systemd service 指定 `scl enable rh-python38 ...`

## 9. 推薦啟動順序

1. 切 repo 到 vault
2. 安裝 `rh-python38`
3. 建立 `.venv`
4. 啟動 `hermes_mcp_server.py`
5. 由 Hermes 呼叫 `tools/list` / `tools/call`

