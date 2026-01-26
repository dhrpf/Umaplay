"""Wine detection and compatibility helpers for running Umaplay under Wine/Linux."""

import os
import sys
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def is_running_under_wine() -> bool:
    """
    Detect if the current Python process is running under Wine.
    
    Returns:
        True if running under Wine, False otherwise.
    """
    # Check for Wine-specific environment variables
    if os.environ.get("WINE") or os.environ.get("WINEPREFIX"):
        return True
    
    # Check for Wine registry keys (Windows API available via pywin32-ctypes)
    try:
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Wine")
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            pass
    except ImportError:
        pass
    
    # Check if running on Linux but Windows APIs are available (Wine scenario)
    if sys.platform.startswith("linux"):
        try:
            import win32api
            # If we can import win32api on Linux, we're likely under Wine
            return True
        except ImportError:
            pass
    
    return False


def get_wine_window_list():
    """
    Get list of windows under Wine environment.
    Wine may have issues with EnumWindows, so we provide a fallback.
    
    Returns:
        List of window handles or empty list if enumeration fails.
    """
    try:
        import win32gui
        windows = []
        
        def enum_callback(hwnd, results):
            if win32gui.IsWindowVisible(hwnd):
                results.append(hwnd)
        
        win32gui.EnumWindows(enum_callback, windows)
        return windows
    except Exception as e:
        logger.warning(f"Wine window enumeration failed: {e}")
        return []


def find_window_wine_compatible(window_title: str) -> Optional[int]:
    """
    Find window by title with Wine compatibility.
    
    Args:
        window_title: The window title to search for.
        
    Returns:
        Window handle (HWND) or None if not found.
    """
    try:
        import win32gui
        
        # Try direct FindWindow first
        hwnd = win32gui.FindWindow(None, window_title)
        if hwnd:
            return hwnd
        
        # Fallback: enumerate all windows
        windows = get_wine_window_list()
        for hwnd in windows:
            try:
                title = win32gui.GetWindowText(hwnd)
                if title.strip() == window_title:
                    return hwnd
            except Exception:
                continue
                
    except Exception as e:
        logger.error(f"Wine-compatible window search failed: {e}")
    
    return None


def patch_pygetwindow_for_linux():
    """
    Patch pygetwindow to work on Linux (even without Wine).
    This prevents the NotImplementedError on Linux systems.
    """
    import sys as sys_module
    
    if not sys_module.platform.startswith("linux"):
        return
    
    try:
        import types
        
        # Create a mock pygetwindow module
        mock_gw = types.ModuleType('pygetwindow')
        
        def getAllWindows():
            """Mock function that returns empty list on Linux."""
            logger.debug("pygetwindow.getAllWindows() called on Linux - returning empty list")
            return []
        
        def getWindowsWithTitle(title):
            """Mock function that returns empty list on Linux."""
            logger.debug(f"pygetwindow.getWindowsWithTitle('{title}') called on Linux - returning empty list")
            return []
        
        mock_gw.getAllWindows = getAllWindows
        mock_gw.getWindowsWithTitle = getWindowsWithTitle
        
        # Inject the mock module
        sys_module.modules['pygetwindow'] = mock_gw
        logger.info("Patched pygetwindow for Linux compatibility")
        
    except Exception as e:
        logger.warning(f"Failed to patch pygetwindow for Linux: {e}")


def patch_win32_for_linux():
    """
    Create mock win32 modules for Linux.
    This allows the code to import but not actually use Windows APIs.
    """
    import sys as sys_module
    
    if not sys_module.platform.startswith("linux"):
        return
    
    try:
        import types
        import ctypes
        
        # Mock ctypes.windll if it doesn't exist
        if not hasattr(ctypes, 'windll'):
            mock_windll = types.SimpleNamespace()
            mock_user32 = types.SimpleNamespace()
            mock_windll.user32 = mock_user32
            ctypes.windll = mock_windll
            logger.debug("Mocked ctypes.windll for Linux")
        
        # Create mock win32 modules
        win32con = types.ModuleType('win32con')
        win32gui = types.ModuleType('win32gui')
        win32api = types.ModuleType('win32api')
        win32process = types.ModuleType('win32process')
        
        # Add common constants
        win32con.SW_RESTORE = 9
        win32con.SW_MINIMIZE = 6
        
        # Add mock functions
        def mock_function(*args, **kwargs):
            logger.debug(f"Mock win32 function called (Linux)")
            return None
        
        win32gui.FindWindow = mock_function
        win32gui.SetForegroundWindow = mock_function
        win32gui.ShowWindow = mock_function
        win32gui.GetWindowText = mock_function
        win32gui.IsWindowVisible = mock_function
        win32gui.EnumWindows = mock_function
        win32gui.GetWindowRect = mock_function
        
        # Inject mock modules
        sys_module.modules['win32con'] = win32con
        sys_module.modules['win32gui'] = win32gui
        sys_module.modules['win32api'] = win32api
        sys_module.modules['win32process'] = win32process
        
        logger.info("Created mock win32 modules for Linux compatibility")
        
    except Exception as e:
        logger.warning(f"Failed to create mock win32 modules: {e}")


# Auto-detect and apply patches on import
_is_wine = is_running_under_wine()
if _is_wine:
    logger.info("Wine environment detected - applying compatibility patches")
elif sys.platform.startswith("linux"):
    logger.info("Linux detected - patching for compatibility")
    patch_win32_for_linux()
    patch_pygetwindow_for_linux()
else:
    logger.debug("Running on native Windows or non-Wine environment")
