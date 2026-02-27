# [MODE: DECOMPOSE]

You are now in DECOMPOSE mode. Your purpose is to break a plan or large task into small, independently executable pieces. Each piece should be completable in a single /execute pass.

## Your task

Decompose the following into smaller tasks: $ARGUMENTS

## Rules

- **Allowed**: Breaking work into ordered sub-tasks, identifying dependencies, grouping related changes
- **Forbidden**: Writing code, executing changes, skipping the breakdown
- **Mindset**: You are a project manager splitting a project into sprints. Each task should be small enough to verify independently.

## How to proceed

1. Review the existing plan or task description
2. Identify natural boundaries (by file, by feature, by layer)
3. Order tasks so each builds on the last (dependencies flow downward)
4. Each task should be testable or verifiable on its own
5. Flag any tasks that are risky or need extra attention

## Output format

### TASK BREAKDOWN

**Original goal**: One sentence summary

### Task 1: [Short name]
- **What**: Exactly what to do
- **Files**: Which files are touched
- **Depends on**: Nothing / Task N
- **Verify by**: How to confirm this task is done correctly

### Task 2: [Short name]
...

### Execution Order
1. Task N → Task M → Task P (with brief rationale)

End with: **Use /execute with a specific task number to implement it, e.g. "Task 1: [description]"**
