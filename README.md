# Hermes MCP Governance Helper

This workspace now contains a small Python CLI that validates a subset of the Hermes MCP governance rules and emits audit records.

## 這個工具的定位

這不是完整的 MCP Server，而是一個輕量的治理檢查器。

它可以在 Hermes 呼叫工具前後，協助做下列事情：

- 驗證 Obsidian 路徑是否安全
- 驗證 Git commit message 格式
- 驗證是否禁止直接 push main
- 產生 audit log JSON
- 列出可改善項目

如果你要的是「Hermes 真的透過 MCP Tool 操作 Obsidian / Git / Qdrant」，那麼還需要再包一層 MCP Server，把實際工具呼叫轉接到這個治理檢查器與後端服務。

## 架設方式

### 1. 環境需求

- Python 3.9+
- 可讀寫的工作目錄
- 若要真的操作 Obsidian Vault，需有 `/data/obsidian-vault` 的掛載或對應路徑

### 2. 取得程式

此工作區已經包含：

- [`hermes_mcp_governance.py`](./hermes_mcp_governance.py)
- [`README.md`](./README.md)

### 3. 執行方式

直接用 Python 執行即可，不需要額外安裝套件。

```bash
python3 hermes_mcp_governance.py improvements
```

### 4. 建議部署位置

若要讓 Hermes 穩定使用，建議把它放在一個固定路徑，並由上層流程呼叫，例如：

- CI pipeline
- 本地 shell wrapper
- MCP Server adapter
- 內部 automation runner

## 真正的 MCP Server

如果你要讓 Hermes 直接透過標準 tool name 互動，請使用 [`hermes_mcp_server.py`](./hermes_mcp_server.py)。

它提供：

- `initialize`
- `tools/list`
- `tools/call`
- `ping`

### 啟動方式

```bash
python3 hermes_mcp_server.py
```

### 交互範例

先列出工具：

```json
{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}
```

呼叫 Obsidian 建檔：

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"obsidian_create_note","arguments":{"path":"APISIX/JWT-Auth.md","content":"# JWT Auth"}}}
```

呼叫 Git 狀態：

```json
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"git_status","arguments":{"repo_path":"."}}}
```

### Hermes 互動建議

Hermes 應該採用這個順序：

1. `tools/list` 取得可用工具
2. `tools/call` 前先做治理檢查
3. 執行工具
4. 寫入 audit log
5. 若文件更新，再觸發 `qdrant_reindex`

### 環境變數

- `HERMES_AUDIT_LOG`：audit log 路徑，預設 `/private/tmp/hermes_mcp_audit.log`
- `HERMES_GIT_REMOTE`：git remote 名稱，預設 `origin`

## Files

- [`hermes_mcp_governance.py`](./hermes_mcp_governance.py)
- [`hermes_mcp_server.py`](./hermes_mcp_server.py)

## Usage

Check rules:

```bash
python3 hermes_mcp_governance.py check --tool obsidian_create_note --path /data/obsidian-vault/APISIX/JWT-Auth.md
python3 hermes_mcp_governance.py check --commit-message "[Hermes] Create APISIX JWT Guide"
python3 hermes_mcp_governance.py check --branch feature/hermes-governance
```

Audit log record:

```bash
python3 hermes_mcp_governance.py audit \
  --user "WT Kho" \
  --tool "obsidian_create_note" \
  --parameters '{"path":"APISIX/JWT-Auth.md"}' \
  --result "Success"
```

List improvements:

```bash
python3 hermes_mcp_governance.py improvements
```

## 與 Hermes 交互方式

### 互動流程

1. 使用者提出需求，例如新增 Obsidian note。
2. Hermes 組裝 tool 呼叫參數。
3. 先跑 `check` 驗證路徑、commit message 或 branch 規則。
4. 驗證通過後再執行實際操作。
5. 成功或失敗後，呼叫 `audit` 輸出紀錄。
6. 若文件有變更，後續再觸發 `qdrant_reindex`。

### 範例互動

新增筆記前先檢查：

```bash
python3 hermes_mcp_governance.py check \
  --tool obsidian_create_note \
  --path /data/obsidian-vault/APISIX/JWT-Auth.md
```

提交前檢查 commit message：

```bash
python3 hermes_mcp_governance.py check \
  --commit-message "[Hermes] Create APISIX JWT Guide"
```

避免直接推送 main：

```bash
python3 hermes_mcp_governance.py check \
  --branch main
```

輸出 audit log：

```bash
python3 hermes_mcp_governance.py audit \
  --user "WT Kho" \
  --agent "Hermes" \
  --tool "obsidian_create_note" \
  --parameters '{"path":"APISIX/JWT-Auth.md"}' \
  --result "Success"
```

### 建議的 Hermes 規則

- 每次 tool 執行前先驗證
- 所有 tool 呼叫都要記 audit log
- 文件變更後要觸發 reindex
- 遇到危險操作時先回傳拒絕原因，不要直接執行

## 可改善項目

1. 將規範轉成 JSON/YAML schema，讓 validator 與外部工具共用。
2. 補齊每個 tool 的參數 schema、回傳 schema、錯誤碼。
3. 增加單元測試，特別是路徑穿越與符號連結場景。
4. 將 audit log 落地到固定儲存位置，支援查詢與追蹤。
5. 把 Qdrant reindex 流程做成事件驅動或背景任務。
6. 補上權限矩陣，清楚定義 agent、user、tool 的允許組合。
7. 增加 dry-run 與 verbose 模式，讓規則違反更容易排查。
