# salamander-reloaded

This isn't fully ready for public use,
I'm slowly moving old stuff to the new bot.

### Want to anyhow?

python3.12
requirements specified in pyproject.toml / pdm.lock

assuming you have pdm

```
pdm install
pdm run salamander --setup
pdm run salamander
```

install the requirements listed in pyproject.toml manually
entrypoint is `src/salamander/cli.py`

### Use a venv!

Seriously, use a venv. This project intentionally uses a personal development
fork of discord.py that may or may not be compatible with your environment.
This has features that may not be in a stable release of discord.py, as well
as a few minor changes that can't be included into discord.py at the current
point in time.

No attempt will be made to support the specific development fork
outside of this bot but part of the use of it is intended to support the
ability to work on features I intend to upstream to discord.py. Errors arising
from it are valid bug reports.


### Don't use this bot as a base (caveat lector)

This bot makes several assumptions about signal handling and non-pathological
behavior of code and dependencies. If you do not personally understand the
entirety of the implications of this, and everything that happens in runner.py
this is not a safe base to develop on top of, and may result in a bot that
can only exit by being killed by a process/task manager.
