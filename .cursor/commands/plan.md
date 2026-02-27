# [MODE: PLAN]

You are now in PLAN mode. Your purpose is to create an exact, exhaustive implementation plan. The plan must be so detailed that no creative decisions remain during execution.

## Your task

Create an implementation plan for: $ARGUMENTS

## Rules

- **Allowed**: Specifying file paths, function names, data structures, technical details, architecture decisions
- **Forbidden**: Writing any code, even examples or snippets
- **Mindset**: You are an architect writing a blueprint. Every decision is made here so execution is mechanical.

## How to proceed

1. Search the codebase to understand current state and patterns
2. Identify every file that needs to change and every new file needed
3. Describe exactly what changes in each file (without writing code)
4. Specify function signatures, data flow, error handling strategy
5. Call out any risks or assumptions
6. Convert everything into a numbered checklist

## Output format

### IMPLEMENTATION PLAN

**Goal**: One sentence summary

**Files to modify**:
- List each file and what changes

**New files**:
- List each new file and its purpose

**Architecture decisions**:
- Key technical choices and why

**Risks / Assumptions**:
- What could go wrong, what are we assuming

### IMPLEMENTATION CHECKLIST

A numbered list where each item is a specific, atomic action:
1. [Specific action with file path and what to do]
2. [Specific action with file path and what to do]
3. ...

End with: **Review this plan. When ready, use /execute to implement it or /decompose to break it into smaller tasks.**
