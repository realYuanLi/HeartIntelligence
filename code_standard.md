# Coding Standard

Use these standards to guide coding behavior across general tasks.

## 1) Keep Files Focused

- Keep each file responsible for a single concern.
- Avoid mixing unrelated responsibilities in the same file.
- Split large files when readability or ownership becomes unclear.

## 2) Keep Code Modular

- Prefer small, composable functions and components.
- Keep interfaces clear and explicit.
- Reuse shared utilities instead of duplicating logic.

## 3) Prioritize Readability

- Write code that is easy to understand without extra context.
- Use descriptive naming for variables, functions, classes, and files.
- Keep control flow straightforward and avoid unnecessary complexity.

## 4) Keep Behavior Predictable

- Make code behavior explicit rather than implicit.
- Handle edge cases intentionally.
- Avoid hidden side effects and surprising mutations.

## 5) Maintain Consistency

- Follow consistent structure, naming, and formatting patterns.
- Align with existing project conventions when available.
- Keep similar problems solved in similar ways.

## 6) Prefer Simplicity

- Choose the simplest solution that satisfies the requirement.
- Avoid premature abstractions and over-engineering.
- Add complexity only when it clearly improves correctness or maintainability.

## 7) Design for Maintainability

- Organize code so future changes are localized and safe.
- Keep dependencies minimal and intentional.
- Remove dead code and avoid leaving temporary artifacts.

## 8) Make Errors Understandable

- Fail clearly and provide useful error messages.
- Validate important assumptions at boundaries.
- Surface errors in a way that supports debugging and recovery.

## 9) Write Intentional Comments

- Use comments to explain why, not what.
- Keep comments accurate and update them with code changes.
- Avoid noisy or redundant comments.

## 10) Preserve Backward Safety

- Avoid changing unrelated behavior while implementing a task.
- Keep public contracts stable unless change is explicitly required.
- Prefer additive changes over breaking changes when practical.

