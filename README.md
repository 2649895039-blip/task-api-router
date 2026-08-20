# 🧠 task-api-router — 任务级 AI 模型路由与成本优化插件

> 给每个任务自动选择最合适的模型，省钱又高效。**按对话收任务**：一次输入 = 一次任务 = 一个独立日志。
> 路由核心与具体 provider 完全解耦，可自由接入任意模型。
> 双宿主开箱即用：**Claude Code 插件 + OpenClaw Skill**，内置工具动作守卫（拦截危险 shell 命令 / 越界写入）。

## 设计原则

```
┌─────────────────────────────────────────┐
│  Router Core（决策核心）                 │
│  本地脚本(0token) → 必要时廉价分类       │
│  → 月榜/成本策略 → model                 │
├─────────────────────────────────────────┤
│  ModelRegistry（注册表，YAML 配置）      │
├─────────────────────────────────────────┤
│  ProviderAdapter（适配器层）             │
│  openai_compat / anthropic              │
└─────────────────────────────────────────┘
```

- 路由逻辑**从不出现 provider 名字**，只操作 model_id
- 新增模型 = 在 `config/models.yaml` 加一条配置，零改代码
- **官方月榜**（`config/ranking.yaml`）：仓库每月人工维护，参考公开榜单和模型报告；插件只读取，不额外调用模型
- **本地脚本优先**：能确定任务类型时 0 token；无法确定时才用用户最便宜的已配置 API 做一次短分类
- **默认不拆任务**：普通任务只进行一次实际执行调用；只有显式 `--plan` 才调用 Planner
- **动作守卫**：Agent 执行 read/search/write/shell 前可本地检查，不需要 API
- **不做记忆 / 不学反馈**：每次任务独立日志，数据干净

## 环境要求

- Python **>= 3.10**
- 一个或多个大模型 API key（OpenAI 兼容 / Anthropic 均可）

## 安装

```bash
pip install -e .          # 提供 task-router 命令
```

也可不安装直接跑（仓库内等价）：

```bash
python -m task_router "写一个 Python 函数解析 JSON"
python plugin.py "写一个 Python 函数解析 JSON"
```

## 配置模型

复制公开模板并填入自己的模型与 key（**key 只放环境变量，不要写进文件**）：

```bash
cp config/models.example.yaml config/models.yaml
# 编辑 config/models.yaml：base_url / api_key_env / cost 等
export DEEPSEEK_API_KEY=sk-...
export CLAUDE_API_KEY=sk-ant-...
task-router --models        # 检查哪些模型已配置可用
```

`config/models.yaml` 已在 `.gitignore`（可含真实 key，不会提交）。未创建时自动回退
到公开模板 `config/models.example.yaml`，开箱即跑。新增模型 = 在 YAML 里加一条配置，
零改代码。

## 插件用法（按对话收任务）

```bash
task-router "写一个 Python 函数解析 JSON"          # 单条任务
task-router                              # 交互模式（每条输入=一次任务）
task-router --list                       # 列出所有运行日志
task-router --show <run_id>              # 查看某个运行日志
task-router --models                     # 列出已注册模型
task-router --plan "重构整个项目"         # 只有明确需要时才拆 DAG
task-router --version
```

## 安装为 Claude Code / OpenClaw 插件

仓库内置**双宿主插件结构**：核心代码只有一份，Claude Code 和 OpenClaw 各用宿主适配层调用。

```
task-api-router/
├── .claude-plugin/
│   └── plugin.json          # Claude Code 插件 manifest
├── hooks/
│   ├── hooks.json           # PreToolUse 动作守卫注册
│   └── action_guard_hook.py # 守卫 hook 脚本
├── skills/
│   └── task-router/
│       └── SKILL.md         # Claude Code skill
└── openclaw/
    └── skills/
        └── task-router/
            └── SKILL.md     # OpenClaw skill
```

### Claude Code

```bash
pip install -e .        # 安装 task-router 命令（首次）
# 在项目里 /tmp/settings.json 启用插件：
claude --plugin <本仓库绝对路径>
# 或把仓库 clone 到项目根，Claude Code 会自动发现 .claude-plugin/
```

安装后：
- **动作守卫**：任何 `Bash` / `Write` / `Edit` 工具调用前，本地检查是否命中
  破坏性命令（`rm -rf`、`git reset --hard`）或工作区外写入，不消耗 token。
- **路由 skill**：Claude 会自动知道用 `task-router "任务"` 执行任务并按模型路由。

### OpenClaw

把 skill 放进 OpenClaw workspace：

```bash
mkdir -p <openclaw-workspace>/skills/task-router
cp openclaw/skills/task-router/SKILL.md <openclaw-workspace>/skills/task-router/
pip install -e .        # 安装 task-router 命令
```

之后 OpenClaw 即可在工具执行前调用同一个守卫：

```bash
task-router --check-action '{"tool":"shell","arguments":{"command":"git reset --hard"}}' --workspace .
```

### 动作守卫接口

任何宿主（Claude Code / OpenClaw / VS Code 等）都可调用同一个本地接口：

```bash
task-router --check-action '{"tool":"write","arguments":{"path":"src/app.py"}}' --workspace .
task-router --check-action '{"tool":"shell","arguments":{"command":"git reset --hard"}}' --workspace .
```

输出为 JSON，退出码 `0=allow`、`2=confirm`、`3=block`。只读动作直接允许；
工作区内写入允许；工作区外写入、未知工具和外部副作用要求确认；明显破坏性命令阻止。
该接口只负责统一判断，各宿主只需把自己的工具名和参数转换成上述 JSON。

> 注意：动作守卫是**本地、尽力而为**的弱校验，只拦截明显危险模式（如 `git reset
> --hard`、`rm -rf`），不是完整沙箱。关键操作请以宿主自身的权限控制为准。

API key 优先读环境变量（如 `DEEPSEEK_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`，具体以你 `models.yaml` 里的 `api_key_env` 为准）。
若设置了 `TASK_ROUTER_API_CONFIG` 环境变量指向本地 JSON，会在启动时自动补齐缺失的 key
（可选便利，开源版不内置任何本机路径）。

## 作为库在脚本里调用

插件同时是可 import 的 Python 包：

```python
from task_router.orchestrator import RouterOrchestrator

orch = RouterOrchestrator("config/models.yaml", "data")
r = orch.run("写一篇关于人工智能的科普文章")
print(r.run_id)        # 独立运行日志 id
print(r.report.total_cost)  # 本次成本
```

> 注意：`orch.run()` 内部用 `asyncio.run()` 包一层，**不能在已运行的事件循环里调用**。
> 如果宿主本身就是 asyncio 程序，请改用 `DAGExecutor.execute_async()` 协程版本。
> 另外子任务用 `asyncio.to_thread` 调模型，取消协程后底层线程会继续跑完（SDK 内部
> 有超时兜底），这是 `to_thread` 的已知特性。

## 模型路由月榜

`config/ranking.yaml` 是**静态路由表**：按任务类型（capability）给出模型相对排序，
执行时只在本机已配置的模型里取第一个可用。仓库里随包发布的是**格式模板**（内含
示例型号与占位排名，明确标注 `status: example`）——请发布前按当月公开榜单替换成
真实数据，模型迭代快，别把示例排名当权威依据。

示例形式如下：

| capability | 示例榜首 | 说明 |
|---|---|---|
| code / reasoning / planning | claude-sonnet | 难任务优先排名靠前的模型 |
| translation / research / bulk / general | gpt-4o-mini | 大量任务优先成本合适的模型 |

> 路由只在本机已配置（`config/models.yaml`）的模型里选：榜首模型若未配置，
> 会自动落到榜单下一个可用的。

榜单来源记录在 `config/ranking.yaml` 的 `sources` 字段（Artificial
Analysis Intelligence Index、LMSYS Chatbot Arena、SWE-bench 等），并按任务类型
使用，不把任何一个来源冒充成“所有能力总榜”。插件不会为了验证榜单而额外调用
模型：明确任务只支付实际执行的一次调用；脚本无法分类时，才增加一次最多 96
output tokens 的廉价分类调用；显式使用 `--plan` 时才增加规划调用。

## 失败降级与熔断

商用环境必须保证“一次调用失败不能拖垮整个 run”：

- **熔断**：本次 run 内某模型调用失败（超时/报错/欠费），后续子任务立即跳过它，
  沿榜单/能力标签回退到下一个可用模型，不再重复撞墙。
- **逐子任务回退**：单个子任务首次调用失败后，会自动尝试下一个可用模型
  （默认最多回退 2 次）。
- **坏依赖保护**：计划中出现引用不存在的子任务或依赖环时，自动修复并显式
  `WARN`，不会静默兜底，也不会死锁。
- **异常隔离**：子任务异常只影响它自己，不拖死整个 run；系统内没有任何可用
  模型时，该子任务直接标记失败，绝不拿已知不可用的模型凑数。

## 安全与数据保护

- **防路径穿越**：`--show` / 交互 `/show` 的 run_id 在读取前校验（只允许纯文件名，
  含 `/` `\` `..` 一律拒绝），不会打开 runs 目录以外的任意文件。
- **日志不覆盖**：run_id 含毫秒 + 序号兜底，同一秒多次运行各自独立存档，历史日志
  绝不静默覆盖。
- **落盘失败不丢数据**：API 费用已发生、结果已算出时，流水/日志写盘失败只打
  `WARN` 并返回结果，不崩溃、不丢已算数据。
- **连接用完即关**：每个模型调用的 HTTP 客户端调用完显式关闭，DAG 高并发下不会
  泄漏文件描述符。
- **上游异常受控**：返回空 choices / 配置缺失都转成受控失败走降级链路，不抛未捕获
  异常炸掉整条 DAG。
- **开箱即用**：`config/models.yaml` 是本地私有配置（已 gitignore，可含真实 key），
  缺失时自动回退到公开模板 `config/models.example.yaml`，新 clone 直接可跑。

## 代码结构

```
task_router/               # 路由核心（与具体宿主解耦）
├── cli.py               # 插件 CLI（task-router 命令 / python -m task_router）
├── orchestrator.py      # 全链路串联（含 RunResult）
├── preclassify.py       # 免费关键词预判（0 token，只做参考）
├── decision.py          # 任务筛选：本地规则或最便宜 API 短分类 → RouteDecision
├── planner.py           # 任务拆解（可选，--plan 时调用）
├── allocator.py         # 静态 ranking 分配器（SubTask → model_id）
├── executor.py          # DAG 并行执行（含熔断/回退）
├── registry.py          # 模型注册表（YAML → ModelConfig）
├── models.py            # ModelConfig / ModelResponse / safe_error_text
├── client.py            # 统一调用入口（按 model_id 路由到对应 adapter）
├── action_guard.py      # Agent 动作本地拦截（--check-action）
├── reporter.py          # 统一流水（history.jsonl）
├── runlog.py            # 独立运行日志（data/runs/<run_id>.json）
├── config/              # 随包发布的公开模板（models.example.yaml / ranking.yaml）
└── adapters/            # provider 适配层（openai_compat / anthropic）

.claude-plugin/          # Claude Code 插件 manifest
hooks/                   # Claude Code PreToolUse 动作守卫 hook
skills/task-router/      # Claude Code skill
openclaw/skills/         # OpenClaw skill
```

## 数据

```
data/
├── runs/<run_id>.json   # 每个任务一个独立日志（对话级）
└── history.jsonl        # 统一流水
```

## 路线图

- [x] M0: ModelRegistry + ProviderAdapter
- [x] M1: Planner 任务拆解
- [x] M2: Allocator 分配
- [x] M3: DAG Executor 并行执行
- [x] M4: Reporter + RunLog（简化：砍 Feedback 学习）
- [x] M5: 静态 ranking + 本地筛查/廉价分类 + 动作守卫
- [x] M6/M7: 本地 API 网关 + 流式（已按用户决定退役并移除）

## License

MIT
