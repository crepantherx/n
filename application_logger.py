import os
import json
from datetime import datetime
from config_loader import get_data_dir

DATA_DIR = get_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = os.path.join(DATA_DIR, "applications_log.json")

def log_application(agent_name: str, company: str, role: str, url: str, details: dict = None):
    """
    Append a successful application to the centralized log.
    details: optional dictionary with extra info (e.g. location, salary expected, application_id)
    """
    if not os.path.exists(LOG_FILE):
        logs = []
    else:
        try:
            with open(LOG_FILE, "r") as f:
                logs = json.load(f)
        except Exception:
            logs = []
            
    entry = {
        "timestamp": datetime.now().isoformat(),
        "agent": agent_name,
        "company": company or "Unknown",
        "role": role or "Unknown",
        "url": url,
        "details": details or {}
    }
    
    logs.append(entry)
    
    # Keep only the last 5000 to prevent file bloat
    if len(logs) > 5000:
        logs = logs[-5000:]
        
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        tmp = LOG_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(logs, f, indent=2)
        os.replace(tmp, LOG_FILE)
    except Exception as e:
        print(f"Failed to write application log: {e}")
