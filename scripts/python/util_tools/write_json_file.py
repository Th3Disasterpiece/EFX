import os
import json
from datetime import datetime
import hou  # Assuming hou module is imported in your environment

def save_json_file(file_name, user_dir):
    core = os.path.join(user_dir, 'descriptions')
    ext = '.json'

    if not os.path.exists(core):
        os.makedirs(core)

    json_path = os.path.join(core, file_name + ext)

    description_data = {
        "Summary": input("Enter summary: "),
        "Keywords": input("Enter keywords (separated by comma): ").split(","),
        "File Name": file_name,
        "Date": datetime.now().strftime("%Y-%m-%d"),
        "Time": datetime.now().strftime("%H:%M:%S"),
        "Size": calculate_size(json_path)
    }

    with open(json_path, 'w') as json_file:
        json.dump(description_data, json_file, indent=4)

def calculate_size(file_path):
    return os.path.getsize(file_path) if os.path.exists(file_path) else 0

# Example usage:
if __name__ == "__main__":
    user_dir = input("Enter user directory path: ")
    file_name = input("Enter file name: ")
    save_json_file(file_name, user_dir)
