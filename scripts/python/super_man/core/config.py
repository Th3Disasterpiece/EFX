import platform
from pathlib import Path

class M1Config:
    def __init__(self):
        self.is_m1 = platform.machine() == 'arm64'
        self.base_path = Path.home() / "Library/Application Support/SuperMan"
        
        if self.is_m1:
            self.houdini_path = Path("/Applications/Houdini/Houdini.app/Contents/Frameworks/Houdini.framework/Versions/Current/Resources")
        else:
            self.houdini_path = Path("/Applications/Houdini/Current/Frameworks/Houdini.framework/Versions/Current/Resources")
