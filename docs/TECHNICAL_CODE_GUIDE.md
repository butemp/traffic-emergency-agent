# 交通应急指挥大模型项目技术文档

## 1. 文档目的

本文档面向参与本项目开发、部署、排障和二次扩展的技术人员，说明当前仓库的真实技术结构、关键模块职责、运行链路、配置依赖和已知实现特点。

本文档基于仓库当前代码实现整理，不以 README 的早期简化描述为准。

## 2. 项目定位

本项目是一个面向交通应急指挥场景的 Agent 系统。它并不是单一的大模型问答应用，而是由以下几部分协同组成：

- 大语言模型：负责理解用户意图、规划工具调用、整合结果并生成最终回答
- Agent Core：负责维护会话状态、调度模型、执行工具调用循环
- 工具层：负责接入法规检索、历史案例、风险评估、媒体理解、地图资源、高德实时数据
- RAG 层：负责从本地法规和预案知识库中做语义检索与精排
- Web/CLI 入口：分别提供面向演示和调试的交互方式

项目的核心价值不在“模型本身知道多少”，而在“模型能否正确调用本地知识与外部工具，为应急指挥提供可操作建议”。

## 3. 总体架构

### 3.1 架构分层

```text
用户
  │
  ├─ CLI: main.py
  └─ Web: web_app.py
        │
        ▼
     Agent Core
        │
        ├─ LLM Provider
        │    └─ OpenAI-compatible API
        │
        ├─ RAG Tool
        │    ├─ Embedding
        │    ├─ Retriever
        │    └─ Reranker
        │
        └─ Domain Tools
             ├─ query_regulations
             ├─ query_historical_cases
             ├─ risk_assessment
             ├─ media_caption
             ├─ search_map_resources
             └─ gaode_tools
                  ├─ geocode_address
                  ├─ reverse_geocode
                  ├─ check_traffic_status
                  ├─ get_weather_by_location
                  └─ search_nearby_pois
```

### 3.2 技术栈

- Python 3
- OpenAI Python SDK
- Typer：CLI
- Chainlit：Web 对话界面
- Transformers + Torch：本地 Embedding 和 Reranker
- Requests：调用高德 Web API
- OpenAI-compatible API：兼容 OpenAI、DashScope 等

## 4. 仓库结构说明

### 4.1 主要目录

```text
traffic-emergency-agent/
├── main.py                         # CLI 入口
├── web_app.py                      # Chainlit Web 入口
├── config/
│   └── settings.yaml               # 早期配置示例，当前代码未完整消费
├── src/
│   ├── agent/                      # Agent 核心
│   ├── providers/                  # 模型调用封装
│   ├── tools/                      # 业务工具
│   ├── rag/                        # RAG 检索实现
│   └── utils/                      # 地图可视化等辅助代码
├── data/
│   ├── regulations/                # 早期法规数据
│   ├── regulations/chunked_json/   # RAG 主知识库
│   ├── historical_cases/           # 历史案例
│   ├── graph/                      # 内部资源地图库
│   ├── conversations/              # 会话记录
│   └── uploads/                    # Web 上传媒体暂存
├── requirements.txt
├── requirements-web.txt
└── requirements-embeddings.txt
```

### 4.2 文档与代码的一致性说明

当前 README 描述的是项目较早阶段的形态，真实代码已经演进为更完整的系统：

- 主文档仍强调三类工具，但实际已有 RAG、地图资源、高德接口、多模态能力
- `config/settings.yaml` 更像示例配置，运行主流程主要依赖环境变量
- `TECHNICAL_ARCHITECTURE.md` 提供了方向性说明，但部分细节和当前代码实现仍有差异

因此，后续维护应优先参考源码和本文档。

## 5. 系统启动方式

### 5.1 CLI 模式

入口文件：`main.py`

支持命令：

- `python main.py interactive`
- `python main.py query "问题内容"`

CLI 的主要作用：

- 调试 Agent 主循环
- 验证模型和工具是否可用
- 快速测试不同 RAG 配置

### 5.2 Web 模式

入口文件：`web_app.py`

典型启动方式：

```bash
chainlit run web_app.py -h 0.0.0.0 -p 8000
```

Web 模式特点：

- 每个会话独立创建 Agent
- 支持中间步骤可视化
- 支持图片/视频上传
- 能展示资源检索结果和地图 HTML
- 相比 CLI，集成能力更完整

## 6. Agent 核心设计

### 6.1 核心职责

`src/agent/agent.py` 中的 `Agent` 负责：

- 保存系统提示词
- 维护会话状态
- 将消息转为 OpenAI-compatible 格式
- 请求模型决策
- 解析并执行工具调用
- 将工具返回结果回灌给模型
- 在若干轮迭代后生成最终回答

### 6.2 Agent 工作循环

主入口方法是 `Agent.chat(user_message)`。

执行流程如下：

1. 将用户消息写入会话历史
2. 读取工具定义并调用模型
3. 若模型返回 `tool_calls`
4. 执行工具，得到工具结果
5. 将工具结果作为 `tool` 消息加入历史
6. 追加一段额外 system 提示，要求模型先分析工具结果再继续
7. 进入下一轮迭代
8. 若模型没有工具调用，则输出最终回答
9. 保存会话到本地 JSON 文件

### 6.3 Prompt 策略

Agent 的系统提示词中显式定义了：

- 角色：交通应急指挥助手
- 优先工具：`query_rag`
- 资源查询优先级：优先内部资源 `search_map_resources`，再考虑公开 POI
- 风险评估触发规则：仅在用户明确要求时调用
- 回答格式：先分析，后建议

这个 Prompt 是系统行为约束的核心。如果后续要调整“先查什么、什么时候停、如何输出”，优先从这里入手。

### 6.4 单工具串行约束

CLI 中的 `Agent` 实现有两个重要限制：

- 每轮只执行第一个工具调用
- 每个工具在一次会话中最多执行一次

这样做的好处：

- 流程稳定
- 防止模型反复调用同一工具进入死循环

代价：

- 复杂问题的探索深度受限
- 某些需要“同一工具多次换参数查询”的场景会被直接抑制

### 6.5 Web 与 CLI 的行为差异

这是一个重要实现细节。

CLI 复用 `Agent.chat()` 的串行约束逻辑。

Web 端没有直接调用 `Agent.chat()`，而是在 `web_app.py` 中重新实现了一套带可视化 Step 的工具循环。其行为特点是：

- 会执行模型返回的全部工具调用，而不只执行第一个
- 每轮调用过程会显示在 Chainlit 步骤面板中
- 工具返回会被做定制化展示

因此，CLI 与 Web 在“工具执行策略”上并不完全一致。调试结果不一致时，应优先检查这个差异。

## 7. 消息模型与会话状态

### 7.1 消息模型

`src/agent/message.py` 定义了三类核心结构：

- `MessageRole`：`system/user/assistant/tool`
- `ToolCall`：工具名、参数、工具调用 ID
- `ChatResponse`：模型文本输出和工具调用结果的统一抽象

### 7.2 会话状态

`src/agent/state.py` 的 `ConversationState` 负责：

- 保存消息列表
- 维护最大历史长度
- 保留 system 消息
- 将会话保存为 `data/conversations/session_*.json`

当前策略是简单截断旧消息，并未做 token 级摘要压缩。

这意味着：

- 长对话时上下文可能快速膨胀
- 虽然有限制历史条数，但没有精确控制 token 消耗

## 8. 模型 Provider 设计

### 8.1 OpenAI-compatible 封装

`src/providers/openai_provider.py` 统一封装了模型访问。

作用：

- 创建 OpenAI SDK 客户端
- 支持传入 `base_url`
- 支持工具调用参数 `tools`
- 将 SDK 返回转为项目内部的 `ChatResponse`

### 8.2 兼容的服务商

通过 OpenAI-compatible 协议，理论上支持：

- OpenAI 官方
- 阿里云 DashScope 兼容接口
- DeepSeek 兼容接口
- 其他 OpenAI-compatible 服务

当前项目默认倾向使用：

- `qwen-plus` 作为主模型
- `qwen-vl-plus` 作为多模态 caption 模型

### 8.3 Provider 自动判断逻辑

代码会基于以下因素推断默认 `base_url`：

- 如果模型名以 `qwen` 开头，偏向 DashScope
- 如果检测到 `OPENAI_API_KEY`，偏向 OpenAI

这是启发式实现，不是严格配置中心。若模型与服务商不匹配，建议显式设置环境变量 `OPENAI_BASE_URL`。

## 9. 工具层设计

工具统一继承 `src/tools/base.py` 中的 `BaseTool`。

每个工具都需要实现：

- `description`
- `parameters`
- `execute(**kwargs)`

然后通过 `to_openai_format()` 转成 Function Calling 所需的 JSON Schema。

### 9.1 query_regulations

作用：

- 从 `data/regulations` 下读取 JSON/JSONL
- 按关键词、事故类型、严重程度过滤

特点：

- 实现简单，属于字段级过滤
- 更像早期版本遗留工具
- 与语义检索相比能力有限

### 9.2 query_historical_cases

作用：

- 从 `data/historical_cases` 加载案例
- 按关键词、事故类型、地点过滤

适合场景：

- 需要参考相似处置经验
- 需要让模型结合“历史案例”组织建议

特点：

- 当前案例规模较小
- 同样属于本地字段过滤

### 9.3 risk_assessment

这是一个“LLM 套 LLM”的工具。

作用：

- 接收 `scenario` 和 `plan`
- 使用预定义 Prompt 对方案评分
- 要求模型按 JSON 结构输出结果

输出通常包含：

- 综合得分
- 风险等级
- 各维度评分
- 潜在风险
- 改进建议

技术特点：

- 本质不是规则引擎，而是 Prompt 约束下的结构化生成
- 如果模型未按 JSON 输出，需要依赖解析容错逻辑
- 结果稳定性受模型质量和提示词约束影响较大

### 9.4 media_caption

作用：

- 对上传图片生成交通应急场景 caption
- 对视频抽帧后进行多图联合理解
- 返回结构化 JSON

支持的输出字段通常包括：

- `caption`
- `key_points`
- `risks`
- `raw`

用途：

- 让现场图片/视频进入 Agent 的可理解上下文
- 将非文本输入转成可继续分析的文本化描述

Web 端在接收到图片/视频上传时，会自动改写用户消息，引导模型先调用 `media_caption`，再结合结果回答。

### 9.5 search_map_resources

作用：

- 从 `data/graph/*.json` 加载内部资源点
- 根据事故点坐标筛选附近资源
- 计算与事故点的球面距离
- 按值班表推算当前联系人

资源类型包括：

- `medical`
- `fire`
- `police`
- `inventory`
- `transport`

输出特点：

- 同时返回给模型看的文本摘要
- 也返回结构化 JSON，供前端做地图展示

这是项目中非常贴近应急指挥业务的一层，因为它体现了“内部可调度资源优先于公开资源”的业务规则。

### 9.6 高德工具集 gaode_tools

`src/tools/gaode_tools.py` 中封装了多个能力。

#### geocode_address

将地址转为经纬度。

典型用途：

- 用户给的是地点描述，不是坐标
- 后续需要查天气、路况、附近资源

#### reverse_geocode

将经纬度转为可读地址。

典型用途：

- 验证坐标位置
- 将设备上报坐标变为可读地点

#### check_traffic_status

调用高德交通圈接口，查询周边拥堵情况。

典型用途：

- 评估事故路段对周边通行的影响
- 辅助救援路线规划

#### get_weather_by_location

先逆地理编码拿到行政区，再查询天气。

典型用途：

- 雨雪雾等恶劣天气对应急处置有明显影响

#### search_nearby_pois

搜索公开兴趣点，如医院、加油站、停车场等。

业务定位：

- 作为内部资源不足时的补充手段
- 不应优先于 `search_map_resources`

## 10. RAG 设计

### 10.1 RAG 在系统中的角色

当前系统的法规、预案、技术指南主检索入口是 `query_rag`，而不是早期 `query_regulations`。

其核心价值在于：

- 不依赖简单关键词匹配
- 直接从切片知识库中做语义召回
- 用 reranker 提高相关性

### 10.2 知识库来源

当前主知识库目录：

- `data/regulations/chunked_json`

该目录下每个 JSON 文档通常包含：

- 文档元信息
- 若干 `chunks`
- 每个 chunk 的文本与 metadata

### 10.3 RAG 组件

RAG 相关代码位于 `src/rag/`：

- `config.py`：配置类与预设模式
- `tool.py`：暴露给 Agent 的工具接口
- `retriever.py`：真正的检索器
- `embedding.py`：文本向量化
- `reranker.py`：精排

### 10.4 检索流程

`query_rag.execute(query)` 的典型处理流程：

1. 将用户问题编码为向量
2. 与所有文档 chunk 向量做相似度计算
3. 取 `coarse_top_k` 个粗排候选
4. 用 reranker 对候选进行精排
5. 截断每段文本长度
6. 返回前 `final_top_k` 条给模型

### 10.5 配置模式

`src/rag/config.py` 内置了几种模式：

- `FAST_RAG_CONFIG`
- `BALANCED_RAG_CONFIG`
- `PRECISE_RAG_CONFIG`
- `COARSE_ONLY_RAG_CONFIG`

核心参数：

- `coarse_top_k`
- `rerank_top_k`
- `final_top_k`
- `use_rerank`
- `max_doc_chars`

### 10.6 当前实现特点

优点：

- 结构简单清晰
- 方便本地直接运行
- 检索逻辑透明，易于调试

局限：

- 启动时直接加载模型并构建全量索引
- 没有向量数据库
- 没有 embedding 持久化缓存
- 文档增量更新能力较弱

当知识库继续扩大后，启动时间和内存占用会成为明显问题。

## 11. Web 端实现说明

### 11.1 核心功能

`web_app.py` 是项目当前功能最完整的交互层。

主要能力：

- 欢迎页和会话初始化
- 每个会话独立 Agent
- 中间思考步骤展示
- 工具调用可视化
- 图片/视频上传
- 地图资源展示

### 11.2 图片和视频处理流程

当 Web 收到附件时，会先判断是否为媒体文件：

- 如果是图片或视频，先复制到 `data/uploads`
- 重写 `message.content`
- 引导模型优先调用 `media_caption`

这是一种非常实用的设计，因为它避免前端先做复杂理解，直接把感知工作交给多模态模型。

### 11.3 Step 可视化机制

Web 端使用 Chainlit 的 `Step` 展示：

- 当前轮次的模型决策
- 正在调用的工具
- 工具参数
- 工具返回摘要

这对演示和排查都非常有用，因为可以看到模型为什么调用某个工具，以及工具到底返回了什么。

### 11.4 地图可视化

`src/utils/map_visualizer.py` 会生成一段高德地图 HTML，用于展示事故点与最近资源点之间的路线。

实现方式：

- 在 HTML 中加载高德 JS API
- 创建地图实例
- 调用驾车路线规划
- 添加起点和终点标记

注意：

- 这里需要高德 JS API Key，与 Web Service Key 不是同一个概念
- 当前实现直接返回 HTML 字符串，属于轻量集成方式

## 12. 数据层说明

### 12.1 法规和预案数据

数据位置：

- `data/regulations`
- `data/regulations/chunked_json`

其中：

- `data/regulations` 主要服务于老工具
- `data/regulations/chunked_json` 是 RAG 主知识库

### 12.2 历史案例

数据位置：

- `data/historical_cases/cases.json`

字段通常包括：

- `title`
- `accident_type`
- `location`
- `date`
- `severity`
- `description`
- `response_actions`
- `outcome`
- `lessons_learned`

### 12.3 内部资源图谱

数据位置：

- `data/graph/resources_01.json`
- `data/graph/resources_02.json`

字段设计说明可参考：

- `MAP_RESOURCES_SCHEMA.md`

这是项目内最接近“业务资产库”的部分，建议后续重点维护数据质量和时效性。

### 12.4 会话记录

位置：

- `data/conversations`

保存内容包括：

- session_id
- 消息历史
- 工具调用记录

用途：

- 调试
- 复盘
- 训练后续提示词或样本积累

## 13. 配置与环境变量

### 13.1 运行主流程依赖的环境变量

当前代码主要依赖环境变量，而不是完整读取 YAML。

核心环境变量如下：

- `DASHSCOPE_API_KEY`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `CAPTION_MODEL`
- `EVAL_MODEL`
- `GAODE_API_KEY`
- `GAODE_JS_API_KEY`
- `GAODE_JS_SECURITY_CODE`

### 13.2 典型配置含义

- `OPENAI_MODEL`：主推理模型
- `CAPTION_MODEL`：多模态媒体理解模型
- `EVAL_MODEL`：风险评估工具内部使用的模型
- `GAODE_API_KEY`：高德 Web 服务接口 Key
- `GAODE_JS_API_KEY`：高德地图 JS 前端 Key

### 13.3 settings.yaml 的实际状态

`config/settings.yaml` 当前更接近示例文件，代码没有完整统一消费它。

如果后续要做工程化改造，建议把：

- 模型配置
- 数据目录
- RAG 参数
- 高德 Key 配置

统一迁移到一个真正被主程序使用的配置中心。

## 14. 依赖说明

### 14.1 基础依赖

`requirements.txt` 主要包含：

- openai
- pydantic
- pyyaml
- python-dotenv
- typer

### 14.2 Web 依赖

`requirements-web.txt` 补充：

- chainlit
- torch
- transformers
- modelscope

### 14.3 Embedding 依赖

`requirements-embeddings.txt` 主要用于模型下载和本地加载：

- modelscope
- torch
- transformers

## 15. 典型调用链路

### 15.1 纯文本应急问答

例如用户提问：

```text
G4 高速发生多车追尾事故，应该如何处置？
```

典型处理流程：

1. 用户消息进入 Agent
2. 模型识别为应急处置问题
3. 优先调用 `query_rag`
4. 必要时补充调用 `query_historical_cases`
5. 模型分析法规依据和历史案例
6. 输出“工具结果分析 + 处置建议”

### 15.2 带地点的资源调度

例如用户提问：

```text
南宁市某高速出口附近发生事故，帮我找最近医院和消防力量
```

典型流程：

1. 模型调用 `geocode_address`
2. 获得经纬度
3. 优先调用 `search_map_resources`
4. 若内部资源不够，再考虑 `search_nearby_pois`
5. 前端可视化最近资源路线

### 15.3 图片/视频现场分析

例如用户上传事故现场图片并提问：

```text
请分析现场风险，并给出处置建议
```

典型流程：

1. Web 层识别上传的是媒体文件
2. 自动改写消息，要求先调用 `media_caption`
3. 模型返回结构化 caption
4. 再基于 caption 调 `query_rag` 或其他工具
5. 输出结构化建议

### 15.4 风险评估

例如用户给出已有方案并要求评估：

1. 模型识别用户明确要求“评估”
2. 调用 `risk_assessment`
3. 工具内部再调用评估模型
4. 返回 JSON 评分结果
5. 模型把评分结果转为解释性回答

## 16. 当前实现中的关键特点与风险

### 16.1 优点

- 架构分层清晰
- 工具职责明确
- Web 端可视化较强
- 业务规则已经初步显式化
- 多模态、知识检索、地图能力已经打通

### 16.2 已知实现问题

#### 1. CLI 中 RAG 配置导入不完整

`main.py` 的 `interactive` 使用了 `FAST_RAG_CONFIG` 等符号，但函数顶部未导入这些名字，存在直接报错风险。

#### 2. RAG 模型路径硬编码

`src/rag/config.py` 默认模型路径写死为 `/workspace/...`，这对本地开发机、其他服务器和容器环境的兼容性较差。

#### 3. GPU 设备号被硬编码

`src/rag/embedding.py` 和 `src/rag/reranker.py` 中将 `CUDA_VISIBLE_DEVICES` 固定为 `7`。这意味着：

- 在没有第 7 号 GPU 的机器上行为不可控
- 在多项目共享 GPU 环境中不够灵活

#### 4. Web 与 CLI 的工具调度逻辑不一致

Web 会执行同轮返回的全部工具，CLI 只执行第一个工具。这会导致：

- 相同问题在不同入口表现不一致
- 线上排查更难统一复现

#### 5. 会话历史控制较粗糙

当前按消息条数控制历史，而不是按 token 控制，也没有摘要压缩。

#### 6. RAG 索引构建成本较高

每次初始化 `QueryRAG` 都会：

- 加载模型
- 读取文档
- 计算所有文档 embedding

这在生产环境中会明显影响启动速度和内存占用。

#### 7. 工具返回格式不完全统一

不同工具返回：

- 有的是 JSON 字符串
- 有的是纯文本
- 有的还带前端专用标记字段

这会增加模型理解成本，也会让前端定制逻辑越来越多。

#### 8. 高德 Key 默认值写在代码中

这在演示环境中可接受，但不适合作为正式生产实现。

### 16.3 运维侧风险

- 外部模型接口调用失败会直接影响主链路
- 高德接口依赖网络和配额
- 多模态模型对大图片/长视频的耗时可能较高
- 本地 RAG 模型和向量索引比较吃显存与内存

## 17. 推荐的后续优化方向

### 17.1 工程化统一

- 统一 CLI 与 Web 的 Agent 调度逻辑
- 建立正式配置中心
- 将工具输出结构统一成标准 JSON

### 17.2 RAG 性能优化

- 预计算并缓存文档向量
- 使用向量数据库或 ANN 索引
- 支持增量导入新文档

### 17.3 可观测性增强

- 为每个请求打 trace_id
- 记录模型耗时、工具耗时、错误率
- 结构化记录工具参数和结果摘要

### 17.4 业务能力升级

- 增加路径规划与预计到达时间
- 增加更细粒度的资源优先级调度
- 增加多轮任务分解与计划执行能力
- 增加法规来源引用与证据链展示

## 18. 新成员快速上手建议

如果是新同事接手项目，建议按下面顺序阅读代码：

1. `web_app.py`
2. `src/agent/agent.py`
3. `src/providers/openai_provider.py`
4. `src/rag/tool.py`
5. `src/rag/retriever.py`
6. `src/tools/search_map_resources.py`
7. `src/tools/gaode_tools.py`
8. `src/tools/media_caption.py`
9. `src/tools/risk_assessment.py`

这样可以先建立主链路，再理解各个专项能力。

## 19. 总结

当前项目已经具备一个应急指挥智能体系统的核心雏形：

- 有通用 Agent 调度框架
- 有领域知识检索能力
- 有地图与实时环境感知能力
- 有多模态现场理解能力
- 有风险评估与资源调度能力

从代码成熟度看，它更接近“功能完整的原型系统”或“面向演示和内部试运行的平台”，而不是完全工程化的生产系统。

如果后续目标是面向真实业务落地，重点不在继续堆更多工具，而在于统一调度逻辑、提升配置与可观测性、优化 RAG 性能、规范数据和输出结构。
