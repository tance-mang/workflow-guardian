# Workflow Guardian

**Know why your unattended automation failed, before you open the logs.**

Workflow Guardian 是一个面向 GitHub Actions 的开源监测工具。它用失败日志和运行状态生成故障报告，帮助维护者定位症状、判断可能原因并安排下一步。

| 基础版（无需 AI） | AI 增强（可选） |
| --- | --- |
| 失败、取消、超时和启动异常报告 | 规则未命中时补充排查建议 |
| 依赖、构建、网络、凭据、限流、上游服务分类 | 结合最近同一工作流的异常次数 |
| 独立漏跑检查、Markdown 报告、可选 SMTP 通知 | 只发送预定义症状类别、结果和异常计数 |

## 在 GitHub Actions 中接入

把以下内容保存为目标仓库的 `.github/workflows/guardian.yml`，并把 `Publish` 改成实际工作流名称。独立监测可覆盖上游任务初始化失败。监测工作流需要在默认分支上。

```yaml
name: Diagnose unattended failures
on:
  workflow_run:
    workflows: [Publish]
    types: [completed]
permissions:
  actions: read
concurrency:
  group: guardian-${{ github.event.workflow_run.id }}-${{ github.event.workflow_run.run_attempt }}
  cancel-in-progress: false
jobs:
  diagnose:
    if: >-
      github.event.workflow_run.head_repository.full_name == github.repository &&
      github.event.workflow_run.head_branch == github.event.repository.default_branch &&
      contains(fromJSON('["failure","timed_out","startup_failure","action_required","cancelled","stale"]'),
      github.event.workflow_run.conclusion)
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: tance-mang/workflow-guardian@v1
```

报告会出现在监测运行的 Summary 和 Artifacts。默认使用通用规则，博客可显式设置 `profile: blog`。生产环境可将 `@v1` 换成已审阅的提交 SHA。监测只接受同仓库默认分支的运行，不执行上游代码，不上传原始日志。GitHub 无法提供日志时，仍会按运行状态生成报告。

| 配置 | 用途 |
| --- | --- |
| `notify: email` | 将 `SMTP_HOST`、`SMTP_USERNAME`、`SMTP_PASSWORD`、`SMTP_FROM`、`SMTP_TO` 作为 Action 步骤的 Secret 环境变量传入。SMTP 使用 TLS 465。 |
| `GUARDIAN_AI_KEY` 和 `GUARDIAN_AI_MODEL` | 将 OpenAI API Key 和模型名作为步骤环境变量传入。调用失败时仍保留规则报告。 |
| `mode: schedule`、`watch-workflow: publish.yml` | 在另一个定时工作流中检查漏跑，使用 `max-age-minutes` 设置容忍时间。检查本身也依赖 GitHub 调度。 |

每次失败以 GitHub Run ID 和 Attempt 标识。按示例设置并发组后，同次运行的通知会检查已保存的发送回执。SMTP 已接收但回执尚未保存时，重试可能重复投递。回执保留 14 天。持续漏跑可在后续巡检中再次报告。

## Python CLI

Python 3.10+，无需安装第三方依赖。在项目根目录执行：

```sh
python -m workflow_guardian analyze path/to/failed.log
python -m unittest discover -s tests -v
```

CLI 本地分析只输出分类、初步判断和修复建议。日志内容留在本机。

## 首个接入项目

[Auto Blog Agent](https://github.com/tance-mang/auto-blog-agent) 负责博客写作、审核和发布。它通过独立工作流调用 Guardian，项目内也提供可复现的故障演练。

MIT 许可，面向自动化开发者开放试用。欢迎提交脱敏故障样例、复现步骤和规则建议。由 tance-mang 发起，OpenAI Codex 协作实现与验证。[反馈入口](https://github.com/tance-mang/workflow-guardian/issues) · [QQ 邮箱](mailto:2123759705@qq.com) · [Gmail](mailto:tance.hub@gmail.com)

## 验证记录

2026-11-05，Guardian 的 6 项本地测试与 [GitHub CI](https://github.com/tance-mang/workflow-guardian/actions/runs/42055028738) 通过。Auto Blog Agent 接入后，[故障演练](https://github.com/tance-mang/auto-blog-agent/actions/runs/42055094513) 按预期失败，[跨仓库监测](https://github.com/tance-mang/auto-blog-agent/actions/runs/42055128853) 成功，已下载报告并确认命中模拟故障及对应尝试次数。[跨仓库漏跑检查](https://github.com/tance-mang/auto-blog-agent/actions/runs/42055103400) 也已成功运行。SMTP 实际投递和真实模型调用待配置后验证。
