# AI 辅助验真解读 - Design

状态：已完成  
关联 Proposal：[proposal.md](proposal.md)  
最后更新：2026-08-21

## 设计摘要

新增独立 `ai_analysis` 模块：把正式证据压缩成无原始行情的请求载荷，通过 OpenAI-compatible API 获取 JSON，使用 Pydantic 和业务规则校验；失败时生成确定性规则解读。报告页负责显式触发和展示，正式报告生成链路不读取 AI 状态。

## 组件职责

| 组件 | 负责 | 不负责 |
| --- | --- | --- |
| `engine/evidence_engine.py` | 计算证据与裁决 | 调用模型 |
| `engine/hash_utils.py` | 分别计算 evidence/report/AI 哈希 | 网络请求 |
| `models/ai_analysis.py` | AI 输出结构契约 | 业务裁决 |
| `engine/ai_analysis.py` | 供应商预设、配置解析、请求构建、模型调用、校验、降级 | 修改正式结论或报告 |
| `pages/08_报告与凭证.py` | 选择非敏感模型配置、显示密钥状态、显式触发与独立展示 | 读取或保存 API Key；把 AI 文本放进正式导出 |

## 数据流

1. 证据引擎生成正式结论和 `EvidenceRecord[]`。
2. 页面构造稳定 `report_payload` 并计算 `report_hash`。
3. 用户点击“生成 AI 辅助解读”。
4. `ai_analysis` 仅提取 factor id、conclusion、dimensions、evidence id、severity、claim、metrics、explanation。
5. 根据页面参数、环境覆盖和供应商预设解析 Chat Completions 配置；缺少密钥或配置不合法时直接规则降级。
6. 解析 JSON，验证结构、引用集合和结论一致性。
7. 生成独立 `ai_analysis_hash` 并展示来源；不回写正式报告载荷。

## 接口契约

### `generate_ai_analysis(...)`

- 输入：`factor_id`、`conclusion`、`evidence_dimensions`、`records`、`evidence_hash`，以及可选 `provider`、`model`、`base_url`；可注入测试 transport。
- 输出：`AIAnalysisResult`，包含 `source`、`model`、`prompt_version`、`summary`、`counter_arguments`、`next_experiments`、`ai_analysis_hash`、`fallback_reason`。
- 错误：对页面不抛出模型/解析错误，统一转为 `rule_fallback`；编程错误仍应在测试中暴露。
- 幂等：规则降级对同一输入保持确定；模型输出按实际响应计算独立哈希。

## 模型配置与协议

### 供应商预设

| ID | 页面名称 | 默认 API 根地址 | 默认模型 |
| --- | --- | --- | --- |
| `openai` | OpenAI | `https://api.openai.com/v1` | `gpt-4.1-mini` |
| `deepseek` | DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| `dashscope` | 通义千问 / DashScope | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| `zhipu` | 智谱 | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| `moonshot` | Moonshot / Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| `siliconflow` | 硅基流动 | `https://api.siliconflow.cn/v1` | `Qwen/Qwen3-8B` |
| `custom` | 自定义 OpenAI-compatible | 页面填写 | 页面填写 |

预设是可覆盖默认值，不是对厂商模型生命周期的承诺。页面允许编辑模型 ID；自定义供应商才显示 Base URL 输入框。非自定义供应商可用环境变量把流量指向合规网关或代理。

### 配置优先级

每个非敏感字段独立按“显式函数/页面参数 > 环境变量 > 供应商预设”解析：

- `FACTORGUARD_LLM_PROVIDER`：可选供应商 ID。
- `FACTORGUARD_LLM_BASE_URL`：可选兼容 API 根地址覆盖，支持 `/v1` 或完整 `/chat/completions` 地址。
- `FACTORGUARD_LLM_MODEL`：可选模型 ID 覆盖。
- `FACTORGUARD_LLM_TIMEOUT`：可选，默认 20 秒，限制 1–60 秒。
- `FACTORGUARD_LLM_API_KEY`：唯一密钥来源，Bearer Token，仅用于请求头。

未设置 `FACTORGUARD_LLM_PROVIDER` 但存在旧版 Base URL/模型配置时，按 `custom` 解析，保持向后兼容。请求使用 `temperature=0`、JSON object 响应格式；正文不含 DataFrame、原始行情、API Key 和本地路径。

### 密钥边界

- 页面只调用布尔状态函数显示 `FACTORGUARD_LLM_API_KEY` 是否存在，不读取密钥值。
- 页面不存在密钥输入控件，密钥不写入 Streamlit session state。
- 注入 transport 只在进程内收到带密钥的 `ModelConfig`；序列化请求正文、AI 返回模型、日志和两类报告哈希均不含密钥。
- 缺少密钥、未知供应商、URL 协议非法或自定义配置不完整时，返回带非敏感原因的 `rule_fallback`。

## 校验规则

- 每条反方质询和实验建议至少引用一个当前 `EvidenceRecord.evidence_id`。
- 引用集合必须是当前证据 ID 集合的子集。
- 模型返回的 `conclusion` 必须与正式结论完全一致。
- 摘要与条目长度、数量有上限，防止异常响应撑爆页面。
- 返回结构、JSON 或业务校验任一失败，使用规则降级并记录非敏感原因。

## 哈希边界

- `evidence_hash`：FactorSpec、快照、配置和计算证据。
- `report_hash`：`evidence_hash` + 确定性 `report_payload`。
- `ai_analysis_hash`：`evidence_hash` + 供应商/模型/来源 + prompt version + 经校验的 AI 解读载荷。

## 发布与回退

- 无数据库迁移；AI 分析只保存在当前会话，不进入 `audit_runs`。
- 无模型配置时系统行为等价于现有离线能力，正式报告不受影响。
- 如需回退，只隐藏 AI 标签页并保留新哈希函数；正式报告契约无需回滚。

## 验证策略

- 单元：哈希边界、请求脱敏、合法/非法响应、引用与结论校验、降级确定性。
- 集成：报告页 AppTest 断言三种正式下载不变、AI 区域可降级渲染。
- 回归：全量 pytest、跨页 AppTest、真实 R001、compileall。
