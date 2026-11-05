---
name: workflow-guardian
description: Diagnose GitHub Actions failures and missing scheduled runs using Workflow Guardian. Use when installing the monitor or interpreting a Guardian incident report.
---

For an existing incident, start with the run ID and attempt in the Markdown report. Compare the reported symptom with the first failing step. Treat suggested causes as hypotheses and verify any external publication before re-running a job.

For installation, use the independent workflow_run example in README.md. Monitor only trusted runs from the same repository's default branch. Pin the Action to a reviewed commit when the monitor receives credentials. Keep raw logs and secrets out of issues and public reports. Only enable AI or SMTP when the repository owner has configured them.
