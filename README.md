# 心舟心理辅导助手

心舟面向心理辅导师，以学生档案为入口，支持咨询记录、人工风险记录和个案跟进。辅导师可以先完成手工业务流程，再按需从档案发起 AI 文书任务；AI 生成的文件经有权辅导师确认后，才会进入档案材料列表，不会自动成为正式咨询记录。

本项目在 Yuxi 的 LangGraph、知识检索与工具能力之上实现心理辅导业务。当前运行入口、权限和数据行为以源码与 [Docker Compose](docker-compose.yml) 为准；[产品约束](docs/develop-guides/counseling-product-contract.md)和[路线图](docs/develop-guides/roadmap.md)分别说明业务边界与后续方向。

## 当前业务入口

- **辅导师**：在“心理辅导档案”中建档，查看学生信息和统一时间线，保存并确认咨询记录草稿，追加更正，记录人工风险，录入固定量表、管理机构内部预约，并结束阶段。从有权访问的档案发起 AI 协作任务后，可审阅生成文件并决定是否收入档案材料。
- **业务管理员**：查看获准的档案最小元数据与部门汇总，处理业务管理事项；该角色不因此获得咨询正文和附件的读取权限。
- **超级管理员**：管理机构及平台配置；该角色不自动获得辅导师的档案正文权限。

业务角色由后端授权，页面入口不构成权限依据。心舟不直接面向来访者聊天，不提供独立诊断、处方或自主危机干预。AI 风险提示由辅导师核实，不能自动改变人工风险等级。

## 本地启动

需要 Docker Engine、Docker Compose v2，以及可用的模型 API Key。开发拓扑默认启动 Web、API、worker、PostgreSQL、Redis、MinIO、Milvus、Neo4j 和沙盒相关服务；首次构建和拉取镜像需要一定时间与网络访问。

```bash
git clone https://github.com/wang97x/counseling.git
cd counseling
./scripts/init.sh
docker compose up --build -d
```

Windows PowerShell 可用 `./scripts/init.ps1` 初始化。初始化脚本会在本地创建 `.env`，填写模型凭据并生成安全密钥；已有部署应保留原有密钥。其他供应商和手动配置方式见[快速开始](docs/intro/quick-start.md)。不要将 `.env` 或真实个案资料提交到仓库。

检查服务：

```bash
docker compose ps
curl --fail http://localhost:5050/api/system/ready
```

就绪接口返回 `status: ready` 后，打开 [Web 界面](http://localhost:5173)，按页面提示初始化管理员并登录。API 文档位于 [http://localhost:5050/docs](http://localhost:5050/docs)。登录后，具有辅导师角色的账号从“心理辅导档案”进入业务工作区；实际可见入口取决于显式授予的角色。

已有环境升级前请先阅读[生产部署与升级](docs/advanced/deployment.md)，核对备份和迁移步骤。

## 代码与文档

| 位置 | 职责 |
| --- | --- |
| [`web/`](web/) | Vue 3 / Vite 前端与心理辅导工作台 |
| [`backend/counseling/`](backend/counseling/) | 档案、身份、记录和业务规则 |
| [`backend/server/`](backend/server/) | FastAPI 路由与服务装配 |
| [`backend/package/`](backend/package/) | Yuxi 智能体、知识检索与工具能力 |
| [`docker-compose.yml`](docker-compose.yml) | 本地开发服务拓扑 |

进一步了解实现边界，见[架构文档](ARCHITECTURE.md)；开发和验证约定见[贡献指南](docs/develop-guides/contributing.md)与[测试规范](docs/develop-guides/testing-guidelines.md)。Yuxi 知识库和 Agent 扩展的使用说明仍保留在 [`docs/`](docs/) 中。

## 许可证

项目采用 [MIT License](LICENSE)。Docker Compose 中的第三方组件遵循各自的许可证；再分发或商业部署前请核对实际镜像版本和相应许可。
