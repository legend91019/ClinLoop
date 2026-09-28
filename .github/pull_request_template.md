<!--
PR title must use Conventional Commits, e.g.
  chore: bootstrap ClinLoop monorepo tooling
  feat: define ClinLoop contracts and state policy
-->

## What changed

<!-- One paragraph. What and why, not a file list. -->

## Task / issue

- Task: <!-- e.g. Task 2 — freeze contracts and state machine -->
- Branch: <!-- foundation | feat/agent-runtime | feat/doctor-console-eval | fix/* | docs/* -->

## Interface changes

<!-- Breaking changes to packages/contracts, apps/api routes or OpenAPI.
     Write "none" if there are none. -->

- [ ] No public contract change
- [ ] `packages/contracts` changed → downstream owners notified (A / B)

## Test evidence

Commands run and their results (paste the summary lines):

```text
$ python -m pytest -q
$ python -m ruff check .
$ npm --prefix apps/web run test -- --run   # if frontend touched
```

## UI evidence

<!-- Screenshot or screen recording for any apps/web change. Write "n/a" otherwise. -->

## Safety checklist

- [ ] 仅使用合成或脱敏数据；未提交真实患者数据
- [ ] 未提交密钥、`.env`、数据库卷或构建产物
- [ ] 无自动诊断 / 治疗推荐 / 医嘱开立修改停止
- [ ] Agent 未直接写状态字段；高风险变化经 Guard 与医生审核
- [ ] 新增 Finding 均携带 `supporting_evidence` 与 `searched_sources`
- [ ] 无证据时不改写为“不存在”，而是“未找到记录”

## Known limitations

<!-- Anything deliberately out of scope, or follow-up work. -->

## Reviewer notes

<!-- Where should the reviewer look first? Any risky hunk? -->
