# 数据安全计算与隐私保护平台

面向数据脱敏、差分隐私、安全聚合与访问审计的数据安全计算与隐私保护平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 脱敏规则 | `mask_rule` | 脱敏规则 | 规则编号、目标字段、脱敏算法 |
| 隐私预算 | `privacy_budget` | 隐私预算 | 预算编号、数据集名称、总预算Epsilon |
| 噪声引擎 | `noise_engine` | 噪声配置 | 配置编号、噪声机制、Epsilon值 |
| 安全聚合 | `secure_agg` | 聚合任务 | 任务编号、数据源列表、聚合函数 |
| 访问审计 | `access_audit` | 审计记录 | 记录编号、访问主体、目标资源 |
| 授权审批 | `grant_approval` | 授权申请 | 申请编号、申请人、目标数据 |
| 分级分类 | `classify_tag` | 分级标签 | 标签编号、数据资源、安全等级 |
| 联邦训练 | `federated_train` | 训练任务 | 任务编号、参与节点、模型类型 |
| 梯度加密 | `gradient_encrypt` | 加密配置 | 配置编号、加密方案、密钥长度 |
| 假名化 | `pseudonym` | 假名映射 | 映射编号、原始标识、假名标识 |
| K匿名检查 | `k_anonymity` | 匿名检查 | 检查编号、数据集名称、准标识符列 |
| 差分查询 | `differential_sql` | 查询记录 | 查询编号、查询语句、查询用户 |
| 密文索引 | `encrypt_index` | 索引条目 | 条目编号、加密域、索引类型 |
| 数据水印 | `watermark` | 水印记录 | 水印编号、目标数据集、水印算法 |
| 同意登记 | `consent_registry` | 同意记录 | 记录编号、数据主体、处理目的 |
| 风险扫描 | `risk_scan` | 扫描任务 | 任务编号、扫描范围、扫描规则 |
| 策略下发 | `deploy_policy` | 策略分发 | 分发编号、策略内容、目标节点 |
| 异常检测 | `anomaly_detect` | 异常规则 | 规则编号、检测维度、检测算法 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 脱敏批次复读与交付闸门（mask_rule ↔ watermark）

脱敏规则页完成一次处理后，在「输出水印复读 · 交付前验证」面板提交**脱敏批次**
（样本编号、处理版本、的确切输出快照）。服务端只对这份确切输出做水印检测，
生成绑定「样本 + 处理版本 + 批次」的**复读回执**；数据水印页依据回执确认这一版
能否正式交付。

关键不变量：

- 回执的 `applies_to` 明确标识 `batch_id / batch_no / sample_code / version`；
  交付资格只认绑定到同一 `batch_id` 的通过回执，某一批通过不能替另一批解锁。
- 同一样本重处理会得到新批次/新版本，旧批次与旧回执保持不变；迟到的旧回执
  交错返回时，前端按响应中的 `batch_id`（缺失时回退本次请求 id）贴回对应行，
  并提示该早先结果仍只可用于旧批次那次交付。
- 缺少水印必需字段（`水印编号` / `水印标记` 等载体字段）的输出判定为不可读，
  批次不可交付：下载按钮禁用，`GET /api/mask-batches/{id}/delivery` 服务端
  同样返回 `403`。

主要接口（同时提供下划线/连字符及 `/api/reread/...` 等别名）：

```text
POST /api/mask-batches                 提交脱敏批次（可带 auto_reread）
GET  /api/mask-batches[?sample_code=]  批次列表（含资格与回执）
POST /api/mask-batches/{id}/reread     对该批次的确切输出做水印检测并生成回执
GET  /api/reread-receipts              复读回执历史
GET  /api/reread/state                 批次 + 回执 + 按样本分组的全量快照
GET  /api/mask-batches/{id}/delivery   正式交付下载（无绑定本批通过回执 → 403）
```

领域：数据工程
子方向：数据分析与数据应用
