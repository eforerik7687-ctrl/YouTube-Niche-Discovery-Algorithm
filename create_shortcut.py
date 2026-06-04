"""Create desktop shortcut for NicheTools."""
import os, sys
import winshell
from win32com.client import Dispatch

desktop = winshell.desktop()
cwd = os.getcwd()

# .bat launcher
bat = os.path.join(desktop, "NicheTools.bat")
with open(bat, "w") as f:
    f.write(f'@echo off\ncd /d "{cwd}"\nstart /b python app.py\nexit\n')

# .lnk shortcut with icon
lnk = os.path.join(desktop, "NicheTools.lnk")
shell = Dispatch("WScript.Shell")
shortcut = shell.CreateShortCut(lnk)
shortcut.TargetPath = bat
shortcut.WorkingDirectory = cwd
shortcut.IconLocation = os.path.join(cwd, "niche_icon.ico")
shortcut.Description = "Niche Research Analyzer"
shortcut.Save()

print(f"Desktop: NicheTools.bat + NicheTools.lnk")
print(f"Pin NicheTools.lnk to taskbar to open like a real app")
