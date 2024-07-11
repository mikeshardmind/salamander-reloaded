# salamander-reloaded

This isn't fully ready for public use,
I'm slowly moving old stuff to the new bot.

### Want to anyhow?

You need zig 0.13
python3.12
requirements specified in pyproject.toml / pdm.lock

assuming you have pdm

```
zig build -p .
pdm install
pdm run salamander --setup
pdm run salamander
```

If you don't have pdm
```
zig build -p .
```

install the requirements listed in pyproject.toml manually
entrypoint is `src/salamander/bot.py`