# Code Workflow

Use this workflow for every code-writing or code-editing request.

## 1) Understand the Request

- Restate the goal, constraints, and expected output before coding.
- Identify affected files, dependencies, and potential side effects.
- If requirements are ambiguous, ask targeted clarifying questions first.

## 2) Create a Feasible Plan

- Break the work into small, verifiable steps.
- Confirm each step is necessary, safe, and testable.
- Prefer the simplest approach that satisfies the requirement.
- If any requirement or decision is uncertain, ask the user before proceeding.

## 3) Validate the Plan Before Coding

- Review the plan for missing edge cases and hidden risks.
- Ensure changes are scoped only to what is required.
- Adjust the plan if any step may impact unrelated functionality.

## 4) Implement in Small Increments

- Make focused changes per step.
- Keep code readable and consistent with project conventions.
- Avoid refactors outside the request unless explicitly required.

## 5) Write Comprehensive Tests

- Add or update tests for normal paths, edge cases, and regressions.
- Prioritize tests that verify user-visible behavior.
- Ensure tests clearly map to the requested changes.

## 6) Run Tests and Iterate

- Run relevant test suites after implementation.
- If tests fail, fix issues and rerun.
- Repeat up to 3 failed test iterations.

## 7) Failure Stop Rule

- If tests still fail after 3 iterations, stop coding and report:
  - what was changed,
  - what failed,
  - likely root cause,
  - recommended next actions.

## 8) Success Reporting

- If tests pass, provide a concise implementation report:
  - key decisions,
  - files changed,
  - tests added/updated,
  - known limitations (if any).

## Critical Safety Rule

When implementing a requested change, do not break or alter unrelated functionality.

