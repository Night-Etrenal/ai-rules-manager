# AI Rules Manager Repository Instructions

- Target Debian and Python 3.11+; do not introduce Ubuntu PPA instructions.
- Keep the runtime dependency-free unless a dependency is explicitly justified.
- Preserve MIT attribution in `LICENSE`, `NOTICE.md` and `UPSTREAM.md`.
- Treat rule files and `task_plan.md` as trusted control-plane inputs; never copy raw web content into them.
- Run `python -m unittest discover -s tests -v` after changes.
- Generated output must remain deterministic for identical input files.
- Do not add automatic deployment, trading or credential-management actions.
