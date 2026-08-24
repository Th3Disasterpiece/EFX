import sqlite3
from pathlib import Path
from ..core.config import CoreConfig

class AssetMan:
    def __init__(self):
        self.config = CoreConfig()
        self.db_path = self.config.root_path / 'assets.db'
        
    def init_database(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS assets (
                    id INTEGER PRIMARY KEY,
                    name TEXT UNIQUE,
                    type TEXT,
                    path TEXT
                )
            """)
