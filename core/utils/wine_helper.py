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


def patch_pygetwindow_for_wine():
    """
    Apply patches to pygetwindow for better Wine compatibility.
    This is called automatically when Wine is detected.
    """
    if not is_running_under_wine():
        return
    
    try:
        import pygetwindow as gw
        
        # Store original function
        original_get_all_windows = gw.getAllWindows
        
        def wine_compatible_get_all_windows():
            """Patched version that handles Wine window enumeration issues."""
            try:
                return original_get_all_windows()
            except Exception as e:
                logger.warning(f"pygetwindow.getAllWindows failed under Wine: {e}")
                # Return empty list as fallback
                return []
        
        # Apply patch
        gw.getAllWindows = wine_compatible_get_all_windows
        logger.info("Applied Wine compatibility patches to pygetwindow")
        
    except ImportError:
        logger.debug("pygetwindow not available, skipping Wine patches")
    except Exception as e:
        logger.warning(f"Failed to patch pygetwindow for Wine: {e}")


# Auto-detect and log Wine environment on import
_is_wine = is_running_under_wine()
if _is_wine:
    logger.info("Wine environment detected - applying compatibility patches")
    patch_pygetwindow_for_wine()
else:
    logger.debug("Running on native Windows or non-Wine environment")
