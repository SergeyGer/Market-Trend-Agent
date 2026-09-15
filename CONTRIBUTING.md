# Contributing to Market & Trend Intelligence Agent

First off, thank you for considering contributing to this project. It means a lot.

This document describes the workflow, expectations, and standards used in this repository. Following it helps keep the project maintainable and pleasant for everyone.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Ways to Contribute](#ways-to-contribute)
- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [Code Style](#code-style)
- [Branching and Commit Messages](#branching-and-commit-messages)
- [Pull Request Process](#pull-request-process)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Features](#suggesting-features)
- [Security](#security)
- [License](#license)

---

## Code of Conduct

By participating in this project, you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md). Please report unacceptable behavior to the maintainers.

---

## Ways to Contribute

- Report bugs and unexpected behavior.
- Suggest new features or improvements.
- Improve documentation.
- Add or expand test coverage.
- Submit pull requests for open issues.

If you are unsure where to start, look for issues labeled `good first issue` or `help wanted`.

---

## Development Setup

### 1. Fork and clone

```bash
git clone https://github.com/<your-username>/Market-Trend-Agent.git
cd Market-Trend-Agent
```

### 2. Create a virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install pytest pytest-asyncio ruff
```

### 4. Configure environment

```bash
cp .env.example .env
```

Fill in `ANTHROPIC_API_KEY` and any optional Notion or Telegram credentials. Never commit your `.env`.

---

## Running Tests

```bash
pytest -q
```

The test suite does not require API keys or network access.

To run a specific test file:

```bash
pytest tests/test_schemas.py -q
```

---

## Code Style

This project uses:

- **Ruff** for linting.
- **Black-compatible formatting** (line length `88`).

Configuration lives in [`pyproject.toml`](pyproject.toml).

Run the linter before opening a pull request:

```bash
ruff check .
```

Optional formatting:

```bash
ruff format .
# or
black .
```

---

## Branching and Commit Messages

### Branch naming

Use a short, descriptive prefix:

```text
feat/add-slack-notifications
fix/notion-property-mapping
docs/update-readme
test/analyzer-retries
```

### Commit messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) style:

```text
feat: add Slack notification support
fix: handle Notion 400 errors with schema mismatches
docs: document Notion setup helpers
test: cover summary truncation edge cases
chore: bump pytest to 9.x
refactor: simplify ingestion deduplication
```

Keep commits focused and atomic.

---

## Pull Request Process

1. Ensure your branch is up to date with the target branch.
2. Make your changes and add or update tests when relevant.
3. Run the full test suite and the linter locally.
4. Open a pull request using the template.
5. Link the issue your PR addresses, if any.

### Pull request checklist

- [ ] Tests pass (`pytest -q`).
- [ ] Lint passes (`ruff check .`).
- [ ] Documentation updated when behavior changes.
- [ ] No secrets or `.env` content committed.
- [ ] The PR description explains **what** and **why**, not just **how**.

---

## Reporting Bugs

Use GitHub Issues and include:

- A clear and descriptive title.
- Steps to reproduce the problem.
- Expected behavior and actual behavior.
- Relevant logs or tracebacks.
- Python version and operating system.
- The exact command you ran.

Please redact API keys and personal data from logs before posting.

---

## Suggesting Features

Open an issue and describe:

- The problem you are trying to solve.
- Your proposed solution.
- Alternatives you considered.
- Any trade-offs or additional context.

---

## Security

If you discover a security vulnerability, **do not** open a public issue. Contact the maintainers privately so it can be addressed before disclosure.

Never commit:

- `.env` files
- API keys or tokens
- `market_trend_agent.db`
- Personal documents

If you accidentally commit a secret, rotate it immediately.

---

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
