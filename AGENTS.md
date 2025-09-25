# Contribution Guidelines for Agents and Humans

These neutral guidelines apply to any software project and are intended for both AI assistants and human contributors. They prioritize clarity, reliability, and shared accountability.

## 1. Commit Hygiene
- Write commit messages using the Conventional Commits prefixes: `feat`, `fix`, `docs`, `test`, or `chore`.
- Keep each commit focused; describe the change, its scope, and its intent.

### Example
```
feat/add-auth: implement token-based login flow
```

## 2. Design Principles
- **Simplicity First**: prefer straightforward, well-explained solutions over clever or complex alternatives.
- Maintain a consistent project structure—follow the established naming conventions (e.g., `snake_case`, `PascalCase`, `kebab-case`), avoid duplicating modules or files, and respect the existing architecture.
- Document non-obvious decisions in comments or Architecture Decision Records (ADRs) so future contributors understand the rationale.

## 3. Branching
- Name branches using the format `type/short-topic`, such as `feat/add-login` or `fix/restore-tests`.
- Branches should represent a single coherent objective to keep history clean and reviews manageable.

## 4. Testing Expectations
- Always run the relevant test suites before committing any changes.
- Add automated tests for every new feature or bug fix; include both unit and integration coverage as appropriate.
- Do not reduce overall test coverage without an agreed plan to restore it.

## 5. Quality Gates
- Enforce linting and formatting via tools such as Ruff or ESLint, and Black or Prettier. Resolve all warnings and eliminate dead code before submission.
- Run security scanners (e.g., Bandit for Python, `npm audit` for JavaScript/TypeScript). Never commit secrets, tokens, or other sensitive credentials.

## 6. Documentation Duties
- Update README files, CHANGELOG entries, and inline documentation when behavior changes or new functionality is introduced.
- Provide thorough docstrings or comments for complex functions, classes, and modules.

## 7. Pull Request Discipline
- Keep pull requests small, focused, and easy to review. Reference the relevant issue or task.
- Clearly explain **what** changed and **why** the change was necessary, including testing evidence.
- Ensure tests and linters pass before requesting human review.

## 8. AI-Specific Responsibilities
- AI-generated code must be complete, executable, and accompanied by passing tests.
- A human maintainer must review and approve AI-generated contributions before they merge.

## 9. Licensing & Headers
- Until an explicit project license is adopted, limit file headers to: `Copyright <year> Contributors`.

## 10. Continuous Improvement
- Treat these guidelines as living documentation. Propose updates when new tools, processes, or insights can improve collaboration.

## 11. Task-Vorlagen
- Vor jeder Implementierung MUSS ein Task nach `docs/task-template.md` erstellt und im PR verlinkt werden (TASK_ID im Titel & in Commits). Dieser Schritt ist verbindlich und wird als eigener Review-Check geprüft.

