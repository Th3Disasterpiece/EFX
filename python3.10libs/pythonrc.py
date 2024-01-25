import os
import sys
import inspect
import hou


print('pythonrc.py triggered')

# Set all root paths
houdini_root      = hou.getenv('EFX')
venv_package_root = f'{houdini_root}/packages/venv/lib/python3.10/site-packages'
otl_root          = f'{houdini_root}/otls'


# Add custom OTL/HDA paths here
otl_paths = [
	f"{otl_root}/dj",
]
# Add all subdirectories under specified OTL paths
for path in otl_paths:
    subdirectories = [f"{path}/{subdir}" for subdir in os.listdir(path) if os.path.isdir(f"{path}/{subdir}")]
    otl_paths.extend(subdirectories)
# Retrieve current HOUDINI_OTLSCAN_PATH and append your paths
current_otlscan_path = hou.getenv("HOUDINI_OTLSCAN_PATH", "")
updated_otlscan_path = ";".join([current_otlscan_path] + otl_paths)



# Set Enviornment Variables

# Add HOUDINI_OTLSCAN_PATH
hou.putenv("HOUDINI_OTLSCAN_PATH", updated_otlscan_path + ';&')

# Add PYTHON_PATH
python_path = f"{venv_package_root}:{os.environ.get('PYTHON_PATH', '')}"
hou.putenv("PYTHON_PATH", python_path)

# Set JOB Variable
hou.allowEnvironmentToOverwriteVariable("JOB", True)
os.environ["JOB"] = '/jobs/'
hou.putenv("JOB",os.environ["JOB"])


# Append Packages to sys.path
if venv_package_root not in sys.path:
	sys.path.append(venv_package_root)
