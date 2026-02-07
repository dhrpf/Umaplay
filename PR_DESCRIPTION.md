# Linux/Wine Support for Umaplay

## What does this PR do?

This PR adds Linux compatibility to Umaplay so it can run natively on Linux or through Wine. I've been testing it on my Linux machine and it works great!

## Changes made

- Added cross-platform window detection using `xdotool` on Linux
- Replaced Windows-specific hotkey library with `pynput` for cross-platform support
- Implemented screenshot capture using `mss` library (works on all platforms)
- Fixed file paths to use forward slashes instead of backslashes (2,864 paths in event_catalog.json)
- Added Wine detection and compatibility helpers
- Created documentation for Linux/Wine setup
- Added test scripts to verify everything works

## Backward compatibility

All existing Windows functionality is preserved - no breaking changes! The code automatically detects the platform and uses the right methods.

## Testing

Tested on:
- ✅ Linux (native) - window detection, screenshots, hotkeys all work
- ✅ Wine environment - game runs and bot works correctly
- ✅ Windows compatibility maintained (no regressions)

## Documentation

- `docs/README.wine.md` - Complete setup guide for Linux/Wine users
- `LINUX_TESTING.md` - Quick start guide with Miniconda setup
- Test scripts included for easy verification

## Dependencies

Added two new Python packages:
- `pynput` - Cross-platform keyboard/mouse input
- `mss` - Fast screenshot capture

Linux users also need `xdotool` for window management:
```bash
sudo apt-get install xdotool  # Ubuntu/Debian
```

## How to test

1. Pull the branch
2. Run `pip install -r requirements.txt`
3. On Linux, run `./test_linux_venv.sh` to verify
4. Everything should work as before on Windows

Let me know if you have any questions or need changes!
