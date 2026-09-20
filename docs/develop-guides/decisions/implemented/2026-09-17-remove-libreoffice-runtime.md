# 按使用场景移除 LibreOffice 运行时

状态：implemented
类型：simplification
Owner：docker/api.Dockerfile

## 问题

API 与 worker 共用的后端镜像安装 LibreOffice Writer、Impress 和 Calc，但运行时只用它完成两类派生动作：把 DOCX/PPTX 转成 PDF 供浏览器预览，以及把旧 XLS 转成现代格式后再提取文本。完整办公套件显著增加镜像、安装时间和供应链表面，且把内容预览和表格文本提取绑定到同一个重量级子进程。

## 决策

Dockerfile 拥有 shipping 镜像依赖，`yuxi.utils.filepreview` 拥有 Office HTML 转换与资源预算，`yuxi.knowledge.parser.unified` 拥有旧 XLS 文本提取。

- DOCX/PPTX 预览使用当前 Python Office 依赖提取文本、表格和常见图片，生成经过转义的结构化 HTML；转换前限制 ZIP 条目、解压大小、压缩比、内嵌图片及 HTML 输出大小，前端继续在 sandbox iframe 中展示。原文件下载保持不变，不承诺像素级还原 Office 排版。
- 旧 XLS 使用轻量 `xlrd` 直接读取工作表并生成 Markdown，不再先转换成 XLSX；DOCX、PPTX 和 XLSX 的知识解析继续由 Docling Slim 负责。
- 删除 LibreOffice 系统包、PDF 转换子进程、转换超时配置和 Office PDF 缓存，不增加外部转换服务。

## 替代方案

- 保留 LibreOffice：版式还原较好，但 API/worker 镜像继续承担完整办公套件的体积、安装和进程管理成本。
- 只保留各格式的 LibreOffice nogui 子包：三个子包仍共享大量基础依赖，不能消除本次运行时负担。
- 引入独立 Office 转换服务：可以隔离重量级依赖，但增加部署、鉴权、失败恢复和运维边界，当前预览需求不值得新增服务。
- 删除 DOCX/PPTX 预览或旧 XLS 支持：最小，但会破坏已有用户入口和文件兼容承诺。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| API/worker 镜像不安装或调用 LibreOffice | 只删包名但仍保留 `soffice` 调用或历史配置 | Dockerfile 与文件预览原语 | `docker compose build api worker`；镜像内命令回读；负向搜索 | 搜索恢复任一 LibreOffice 包或执行入口即失败 | Not run（当前宿主无 Docker；源码负向搜索已检查） |
| DOCX/PPTX 返回有资源预算且安全转义的 HTML，原下载不变 | ZIP 解压膨胀、HTML 注入或下载被替换为派生内容 | `yuxi.utils.filepreview` 与 preview service | Preview unit；Workspace HTTP integration；Web 定向 unit | 加密条目、高压缩比、过多或过大条目、总解压量、图片、HTML、非法 ZIP 与 HTML 标签输入必须明确失败 | Not run（当前宿主无 uv/pytest；Python 语法检查、Web 定向 unit 与 build 已通过） |
| 旧 XLS 在无 LibreOffice 时仍提取真实 fixture 内容 | 测试因缺少 LibreOffice 被跳过，或只验证 mock | `yuxi.knowledge.parser.unified` | 真实 `.xls` fixture 单测；镜像内回读 `xlrd==2.0.2` | 损坏 XLS 明确失败，不伪装为空文档 | Not run（当前宿主无 uv/pytest） |
| 删除 PDF 转换缓存与相关配置 | 新方案叠加在旧缓存/子进程之上 | workspace/knowledge preview | 负向搜索与相关 unit | 恢复缓存目录、PDF 对象写入或超时配置即失败 | Not run（当前宿主无 uv/pytest；源码负向搜索已检查） |

旧能力不存在：shipping Dockerfile、Python 源码和活动文档中不存在 LibreOffice/soffice 执行依赖；Office 预览不再生成或缓存 PDF，旧 XLS 不再通过格式转换解析。

重新引入条件：只有产品明确要求在服务端像素级还原复杂 Office 版式，轻量 HTML 预览不能满足已量化样例，并能接受独立转换组件的镜像、隔离、超时和维护成本时，才重新评估 LibreOffice 或专用转换服务。

## 后果

- HTML 预览保留文本、表格和常见图片而非 Office 渲染版式，复杂页眉页脚、动画、图表和精确分页可能缺失。
- `xlrd` 只负责旧 XLS；它不会替代现有 XLSX backend，包含宏或非常规对象的旧表格只保证单元格文本提取。
- 预览由 PDF 二进制响应改为 JSON HTML，前后端必须同步发布并覆盖知识库、Workspace 与 artifact 共用入口。
