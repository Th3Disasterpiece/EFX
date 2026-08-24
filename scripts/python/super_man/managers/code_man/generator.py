from pathlib import Path
from ..core.config import CoreConfig

class CodeMan:
    def __init__(self):
        self.config = CoreConfig()
        
    def generate_module(self, name: str, manager: str):
        """Create new module for a manager"""
        target = self.config.get_manager_path(manager) / name
        target.mkdir(exist_ok=True)
        
        # Create __init__.py
        (target / '__init__.py').touch()
        print(f"Created module: {target}")
        
    def update_core(self):
        """Update shared core components"""
        core_path = self.config.root_path / 'core'
        shutil.copytree('templates/core', core_path, dirs_exist_ok=True)
