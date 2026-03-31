# 交通应急Agent

基于 Agentic LLM 的交通应急响应辅助系统。

## 项目简介

交通应急Agent是一个能够理解应急场景、查询相关法规、参考历史案例、评估风险的智能助手。系统通过工具调用（Function Calling）实现：

- **查询法规/预案**: 根据事故类型和严重程度查询相关法规和应急预案
- **查询历史案例**: 参考类似历史案例的处置经验
- **风险评估**: 对应急方案进行多维度风险评估

## 系统架构

```
┌─────────┐   ┌──────────────┐   ┌───────────┐
│  用户   │──▶│  Agent Core  │──▶│ OpenAI    │
└─────────┘   └──────────────┘   │   API     │
                    │             └───────────┘
                    ▼
        ┌───────────────────────┐
        │      工具层            │
        ├───────────────────────┤
        │ • query_regulations   │
        │ • query_historical    │
        │   _cases              │
        │ • risk_assessment     │
        └───────────────────────┘
                    ▼
        ┌───────────────────────┐
        │    本地数据层          │
        │  • data/regulations/  │
        │  • data/historical_   │
        │    cases/             │
        └───────────────────────┘
```

## 快速开始

### 1. 安装依赖

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置API Key

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑.env文件，填入你的API Key
# 阿里云百炼（推荐）:
# DASHSCOPE_API_KEY=sk-xxx
#
# 或OpenAI:
# OPENAI_API_KEY=sk-xxx
```

### 3. 运行

#### 方式1: Web界面（推荐）🎨

```bash
# Linux/Mac
./start_web.sh

# Windows
start_web.bat

# 或手动启动
pip install -q -r requirements-web.txt
chainlit run web_app.py
```

访问: http://localhost:8000

#### 方式2: 命令行界面

```bash
# 交互模式
python main.py interactive

# 单次查询
python main.py query "高速公路发生多车追尾事故，应该如何处置？"
```

## 使用示例

### 交互模式

```bash
$ python main.py interactive
====================================================
  交通应急指挥助手 - 交互模式
====================================================
输入 'quit' 或 'exit' 退出
输入 'reset' 清空对话历史

你: G4高速发生多车追尾，应该如何处置？

助手: 我来帮你查询相关的处置方案...

[Agent调用工具查询法规和历史案例]

根据查询结果，建议采取以下措施：
1. 立即启动二级应急响应
2. 调派消防、医疗、交警等救援力量
3. 实施交通管制，引导车辆绕行
...
```

### 单次查询

```bash
$ python main.py query "高速公路危化品运输车侧翻泄漏，应该如何处置？"
```

## 项目结构

```
traffic-emergency-agent/
├── src/
│   ├── agent/              # Agent核心
│   │   ├── agent.py        # Agent主类
│   │   ├── message.py      # 消息模型
│   │   └── state.py        # 对话状态管理
│   ├── providers/          # LLM Provider
│   │   └── openai_provider.py
│   ├── tools/              # 工具实现
│   │   ├── base.py         # 工具基类
│   │   ├── query_regulations.py
│   │   ├── query_historical_cases.py
│   │   └── risk_assessment.py
│   └── utils/              # 工具函数
├── data/                   # 数据目录
│   ├── regulations/        # 法规/预案数据
│   ├── historical_cases/   # 历史案例数据
│   └── conversations/      # 对话历史
├── config/                 # 配置文件
├── main.py                 # CLI入口
├── requirements.txt
├── .env.example
└── README.md
```

## 数据格式

### 法规/预案格式 (data/regulations/*.json)

```json
{
  "id": "reg_001",
  "title": "高速公路交通事故应急预案",
  "category": "应急预案",
  "accident_type": "交通事故",
  "severity": "重大",
  "content": "当高速公路发生重大交通事故时...",
  "keywords": ["高速公路", "交通事故", "封闭"],
  "effective_date": "2023-01-01"
}
```

### 历史案例格式 (data/historical_cases/*.json)

```json
{
  "id": "case_001",
  "title": "G4高速多车追尾事故处置案例",
  "accident_type": "交通事故",
  "location": "G4高速K1234处",
  "date": "2023-06-15",
  "severity": "重大",
  "description": "雨天路滑，发生20车连环追尾...",
  "response_actions": [
    "立即启动二级应急响应",
    "调派救援力量..."
  ],
  "outcome": "6小时后恢复通车",
  "lessons_learned": "雨天需提前发布预警..."
}
```

## 配置说明

配置文件：`config/settings.yaml`

```yaml
openai:
  api_key: "${OPENAI_API_KEY}"
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o"
  temperature: 0.7

data_paths:
  regulations: "data/regulations"
  historical_cases: "data/historical_cases"
  conversations: "data/conversations"
```

## 兼容其他API

本系统兼容所有OpenAI格式的API，如：

- **DeepSeek**: 设置 `OPENAI_BASE_URL=https://api.deepseek.com/v1`
- **Azure OpenAI**: 设置对应的Azure endpoint
- **其他兼容API**: 修改 `base_url` 即可

## 日志

日志文件：`agent.log`

```log
2023-12-23 10:30:00 - __main__ - INFO - 初始化Agent: 工具数量=3
2023-12-23 10:30:05 - src.agent.agent - INFO - 用户输入: 高速发生事故...
2023-12-23 10:30:06 - src.agent.agent - INFO - 执行工具: QueryRegulations
...
```

## 注意事项

1. 所有回答基于工具查询结果，不编造信息
2. 对话历史会保存到 `data/conversations/`
3. 建议定期更新法规和案例数据
4. API调用会消耗费用，请注意控制

## 开发计划

- [x] 基础框架实现
- [x] 三大工具实现
- [x] CLI界面
- [ ] Web界面（可选）
- [ ] 更多工具扩展
- [ ] 性能优化

## 许可证

MIT License
