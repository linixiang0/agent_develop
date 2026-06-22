# EduRAG-Agent 评估报告

## 汇总指标

- 测试用例数：25
- 平均关键词命中率：1.0
- 平均来源命中率：1.0
- 平均耗时：12018.28 ms

## 明细

| ID | 关键词命中率 | 来源命中率 | 耗时 ms | 命中关键词 | 缺失关键词 | 首个来源 |
|---|---:|---:|---:|---|---|---|
| cs599-deadline | 1.00 | 1.00 | 11011 | 2026 年 6 月 22 日、23:00、GitHub | - | cs599_course_requirements / 时间节点 |
| cs599-report-chapters | 1.00 | 1.00 | 12049 | 选题背景、Specs、系统架构、测试与评估、课程总结 | - | cs599_course_requirements / 报告要求 |
| cs599-private-repo | 1.00 | 1.00 | 10803 | qxr777、Collaborator | - | cs599_course_requirements / GitHub 仓库要求 |
| cs599-core-tech | 1.00 | 1.00 | 11793 | SDD、Function Calling、记忆机制、状态管理、可观测性 | - | cs599_course_requirements / 核心技术要素 |
| cs599-bonus | 1.00 | 1.00 | 11347 | MCP、Agentic RAG、云服务器、生产级 | - | cs599_course_requirements / 评分标准 |
| cs599-pdf-navigation | 1.00 | 1.00 | 11172 | PDF、导航、书签、目录 | - | cs599_course_requirements / 报告要求 |
| student-status-suspension | 1.00 | 1.00 | 12350 | 休学、导师、学院、证明 | - | real_public_grad_service_knowledge / REAL-0001 学籍管理：休学申请 |
| student-status-return | 1.00 | 1.00 | 12485 | 复学、导师、学院、学籍 | - | synthetic_campus_knowledge / KB-0001 学籍异动：休学申请 |
| training-plan-change | 1.00 | 1.00 | 11334 | 培养计划、变更、导师、学院 | - | real_public_grad_service_knowledge / REAL-0008 培养计划：变更流程 |
| course-retake | 1.00 | 1.00 | 12209 | 重修、补修、培养方案、学分 | - | real_public_grad_service_knowledge / REAL-0013 课程管理：重修与补修 |
| exam-deferral | 1.00 | 1.00 | 11781 | 缓考、申请、任课教师、教务 | - | real_public_grad_service_knowledge / REAL-0011 课程管理：缓考申请 |
| thesis-proposal | 1.00 | 1.00 | 10974 | 研究背景、研究方法、技术路线、进度计划 | - | synthetic_campus_knowledge / KB-0019 学位论文：论文开题 |
| midterm-check | 1.00 | 1.00 | 12290 | 课程学分、科研进展、论文、学术规范 | - | synthetic_campus_knowledge / KB-0010 培养计划：中期考核 |
| pre-defense | 1.00 | 1.00 | 10938 | 论文初稿、查重、导师意见、PPT | - | real_public_grad_service_knowledge / REAL-0016 学位论文：预答辩准备 |
| thesis-review | 1.00 | 1.00 | 12043 | 导师审核、资格审查、学术不端、格式 | - | real_public_grad_service_knowledge / REAL-0017 学位论文：盲审送审 |
| defense-eligibility | 1.00 | 1.00 | 12059 | 课程学分、培养环节、论文评阅、学术规范 | - | real_public_grad_service_knowledge / REAL-0018 学位论文：答辩资格 |
| thesis-misconduct | 1.00 | 1.00 | 11705 | 作假、答辩无效、学位、处分 | - | real_public_grad_service_knowledge / REAL-0021 学术规范：论文作假后果 |
| ai-disclosure | 1.00 | 1.00 | 11580 | AI、核验、disclosure、原创 | - | real_public_grad_service_knowledge / REAL-0023 学术规范：AI 工具使用 |
| national-scholarship | 1.00 | 1.00 | 12947 | 学业成绩、科研、综合表现、公示 | - | real_public_grad_service_knowledge / REAL-0025 奖助管理：研究生国家奖学金 |
| teaching-assistant | 1.00 | 1.00 | 13110 | 答疑、批改作业、泄露试题、评分 | - | real_public_grad_service_knowledge / REAL-0027 奖助管理：助教岗位 |
| vpn-service | 1.00 | 1.00 | 13718 | VPN、WebVPN、授权资源、共享账号 | - | real_public_grad_service_knowledge / REAL-0036 信息服务：校园 VPN |
| library-database | 1.00 | 1.00 | 12247 | 电子资源、批量下载、封禁、版权 | - | real_public_grad_service_knowledge / REAL-0039 图书馆服务：电子资源访问 |
| ethics-review | 1.00 | 1.00 | 12290 | 人体、问卷、个人信息、伦理审查 | - | real_public_grad_service_knowledge / REAL-0043 科研训练：伦理审查 |
| support-path | 1.00 | 1.00 | 12420 | 导师、学院、研究生院、截图 | - | real_public_grad_service_knowledge / REAL-0045 教务咨询：问题升级路径 |
| source-transparency | 1.00 | 1.00 | 13802 | 公开、摘要、合成、透明度 | - | real_public_grad_service_knowledge / REAL-0049 CS599 项目：真实资料与合成资料区分 |
