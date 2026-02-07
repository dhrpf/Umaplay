# Quick Start: Testing Wine Support on Linux

## Prerequisites

- Linux distribution (Ubuntu, Fedora, Arch, etc.)
- Miniconda or Anaconda
- Git

## ✅ Already Verified

The Wine support implementation has been tested on Linux and all tests pass:
- Wine detection works
- Hotkey manager uses pynput correctly
- All modules import without errors
- Conda environment setup works

## 🚀 Quick Test (No Wine Required)

### 1. Install Miniconda (if not already installed)

```bash
# Download and install Miniconda
mkdir -p ~/miniconda3
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O ~/miniconda3/miniconda.sh
bash ~/miniconda3/miniconda.sh -b -u -p ~/miniconda3
rm ~/miniconda3/miniconda.sh

# Initialize conda for your shell
~/miniconda3/bin/conda init bash
# Then restart your terminal or run:
source ~/.bashrc
```

### 2. Set up Conda environment

```bash
# Navigate to Umaplay directory
cd /path/to/Umaplay

# Create conda environment
conda create -n env_uma python=3.10

# Activate environment
conda activate env_uma

# Install dependencies
pip install -r requirements.txt
```

### 3. Run automated test

```bash
# Run the test script
./test_linux_venv.sh
```

This verifies all Wine support code works on Linux.

## 🍷 Full Wine Test (With Umamusume)

### 1. Install Wine

**Ubuntu/Debian:**
```bash
sudo apt install wine winetricks
```

**Arch:**
```bash
sudo pacman -S wine winetricks
```

### 2. Set up Wine prefix

```bash
export WINEPREFIX="$HOME/.wine-umamusume"
export WINEARCH=win64
wineboot -u
```

### 3. Install Python in Wine

```bash
cd ~/Downloads
wget https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe
wine python-3.10.11-amd64.exe
```

### 4. Install Umaplay dependencies in Wine

```bash
cd /path/to/Umaplay
wine python -m pip install -r requirements.txt
```

### 5. Install Umamusume via Steam in Wine

```bash
winetricks steam
wine ~/.wine/drive_c/Program\ Files\ \(x86\)/Steam/Steam.exe
# Install Umamusume: Pretty Derby from Steam
```

### 6. Run Umaplay

```bash
wine python main.py
```

## 📋 Test Results

Current status on Linux (native, no Wine):
- ✅ All modules load correctly
- ✅ Hotkey manager selects pynput
- ✅ Wine detection functional
- ✅ No import errors
- ✅ Virtual environment works

## 📚 Full Documentation

See `docs/README.wine.md` for complete setup instructions, troubleshooting, and configuration tips.

## 🐛 Troubleshooting

**Issue: "No keyboard library available"**
- Expected on Linux without Wine
- Hotkey manager will use pynput instead

**Issue: Import errors**
- Run: `./test_linux_venv.sh` to verify setup
- Check: `source venv_test/bin/activate`

**Issue: Wine not detected**
- Set: `export WINEPREFIX=/path/to/wine`
- Verify: `python -c "from core.utils.wine_helper import is_running_under_wine; print(is_running_under_wine())"`

## ✅ Verification

Run the test suite:
```bash
python test_wine_support.py
```

All tests should pass.
