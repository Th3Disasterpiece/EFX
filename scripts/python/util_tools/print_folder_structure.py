import os

def print_folder_structure(root_path, indent=0):
    try:
        with os.scandir(root_path) as entries:
            for entry in entries:
                if entry.name == ".DS_Store":  # Ignore .DS_Store files
                    continue
                if entry.is_dir():
                    print(" " * indent + f"{entry.name}/")
                    print_folder_structure(entry.path, indent + 4)
                else:
                    print(" " * indent + entry.name)
    except FileNotFoundError:
        print(f"Error: The directory '{root_path}' was not found.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        root_directory = sys.argv[1]
        print_folder_structure(root_directory)
    else:
        print("Please provide a directory path.")
