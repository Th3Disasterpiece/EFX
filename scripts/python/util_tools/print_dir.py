def print_folder_structure(root_path, indent=0):
    try:
        with os.scandir(root_path) as entries:
            for entry in entries:
                if entry.is_dir():
                    print(" " * indent + f"{entry.name}/")
                    print_folder_structure(entry.path, indent + 4)
                else:
                    print(" " * indent + entry.name)
    except FileNotFoundError:
        print(f"Error: The directory '{root_path}' was not found.")

import os

root_directory = "/Users/deepak/jobs/lib/packages/EFX/scripts/python/snip_ui"
print_folder_structure(root_directory)
