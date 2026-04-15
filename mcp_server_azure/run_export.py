import sys
import subprocess
import os

script_path = r"C:\Users\jlmunoz\.agents\skills\export_revit_data\scripts\export_to_excel.py"
data_file = r"C:\Users\jlmunoz\OneDrive - Autoridad del Canal de Panama\Documents\INIO-CE\python_scripts\my_revit_mcp_server\temp_data.json"

with open(data_file, "r", encoding="utf-8") as f:
    json_data = f.read()

subprocess.run(["python", script_path, json_data])
