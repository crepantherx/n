#!/usr/bin/env python3
"""
Naukri Job Applier - macOS GUI Application
A user-friendly interface for automated job applications on Naukri.com
"""

import os
import sys
import json
import threading
import subprocess
import queue
from datetime import datetime, date, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from tkinter import font as tkfont
from typing import Optional

from config_loader import get_data_dir

# Get the directory where the script is located
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = get_data_dir()
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
STATS_FILE = DATA_DIR / "stats.json"
LOG_FILE = LOG_DIR / "job_applier.log"
APPLIER_SCRIPT = SCRIPT_DIR / "naukri_job_applier.py"
BOT_SCRIPT = SCRIPT_DIR / "naukri_bot.py"
BOT_STATS_FILE = DATA_DIR / "naukri_bot_stats.json"
LINKEDIN_APPLIER_SCRIPT = SCRIPT_DIR / "linkedin_job_applier.py"
LINKEDIN_STATS_FILE = DATA_DIR / "linkedin_stats.json"
INTL_LINKEDIN_SCRIPT = SCRIPT_DIR / "intl_linkedin_applier.py"
INTL_INDEED_SCRIPT = SCRIPT_DIR / "intl_indeed_applier.py"
INTL_REED_SCRIPT = SCRIPT_DIR / "intl_reed_applier.py"
INTL_CRAWLER_SCRIPT = SCRIPT_DIR / "intl_career_page_crawler.py"
INTL_STATS_FILE = DATA_DIR / "intl_stats.json"

# Helps confirm which copy is running (script vs packaged app)
APP_BUILD = datetime.fromtimestamp(Path(__file__).stat().st_mtime).strftime("%Y-%m-%d %H:%M")


class Config:
    """Manages app configuration"""
    
    def __init__(self, config_file: Path):
        self.config_file = config_file
        self.data = self.load()
    
    def load(self) -> dict:
        """Load configuration from file"""
        data = {}
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
            except:
                pass
        
        # Set defaults
        if not data:
            data = {
                "email": "",
                "password": "",
                "resume_path": "",
                "job_titles": "ML Engineer, AI Engineer, Software Engineer",
                "schedule_times": ["09:00", "19:00"],
                "bot_schedule_times": ["09:00", "14:30", "21:00"],
                "linkedin_email": "",
                "linkedin_password": "",
                "linkedin_phone": "",
                "linkedin_schedule_times": [],
                # UI preferences
                "ui_headless_naukri": True,
                "ui_headless_bot": True,
                "ui_headless_linkedin": True
            }
        
        # Fallback to .env for LinkedIn credentials if not in config.json
        env_file = SCRIPT_DIR / ".env"
        if env_file.exists():
            from dotenv import load_dotenv
            load_dotenv(env_file)
            
            # Only use .env if LinkedIn credentials are empty in config
            if not data.get("linkedin_email"):
                data["linkedin_email"] = os.getenv("LINKEDIN_EMAIL", "")
            if not data.get("linkedin_password"):
                data["linkedin_password"] = os.getenv("LINKEDIN_PASSWORD", "")
            if not data.get("linkedin_phone"):
                data["linkedin_phone"] = os.getenv("LINKEDIN_PHONE", "")
        
        # Ensure all LinkedIn fields exist
        data.setdefault("linkedin_email", "")
        data.setdefault("linkedin_password", "")
        data.setdefault("linkedin_phone", "")
        data.setdefault("linkedin_schedule_times", [])
        data.setdefault("ui_headless_naukri", True)
        data.setdefault("ui_headless_bot", True)
        data.setdefault("ui_headless_linkedin", True)
        
        return data
    
    def save(self):
        """Save configuration to file"""
        with open(self.config_file, 'w') as f:
            json.dump(self.data, f, indent=2)
    
    def is_configured(self) -> bool:
        """Check if credentials are configured"""
        return bool(self.data.get("email") and self.data.get("password"))


class JobApplierStats:
    """Manages application statistics"""
    
    def __init__(self, stats_file: Path):
        self.stats_file = stats_file
        self.data = self.load()
    
    def load(self) -> dict:
        """Load statistics from file"""
        if self.stats_file.exists():
            try:
                with open(self.stats_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        
        return {
            "total_applications": 0,
            "today_count": 0,
            "last_run": None,
            "success_count": 0,
            "daily_history": {}
        }
    
    def save(self):
        """Save statistics to file"""
        with open(self.stats_file, 'w') as f:
            json.dump(self.data, f, indent=2)
    
    def update_today(self, count: int):
        """Update today's application count"""
        today = str(date.today())
        
        # Reset if it's a new day
        if self.data.get("last_run") != today:
            self.data["today_count"] = 0
        
        self.data["today_count"] += count
        self.data["total_applications"] += count
        self.data["success_count"] += count
        self.data["last_run"] = today
        
        # Update daily history
        if today not in self.data["daily_history"]:
            self.data["daily_history"][today] = 0
        self.data["daily_history"][today] += count
        
        self.save()
    
    def get_week_total(self) -> int:
        """Get total applications for this week"""
        # Simple implementation: sum last 7 days
        total = 0
        for i in range(7):
            day = str(date.today() - timedelta(days=i))
            total += self.data["daily_history"].get(day, 0)
        return total


class NaukriBotStats:
    """Manages naukri bot statistics"""
    
    def __init__(self, stats_file: Path):
        self.stats_file = stats_file
        self.data = self.load()
    
    def load(self) -> dict:
        """Load statistics from file"""
        if self.stats_file.exists():
            try:
                with open(self.stats_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        
        return {
            "last_run": None,
            "success_count": 0,
            "failed_count": 0,
            "total_runs": 0
        }
    
    def save(self):
        """Save statistics to file"""
        with open(self.stats_file, 'w') as f:
            json.dump(self.data, f, indent=2)
    
    def update_run(self, success: bool):
        """Update run statistics"""
        self.data["total_runs"] += 1
        self.data["last_run"] = str(datetime.now())
        
        if success:
            self.data["success_count"] += 1
        else:
            self.data["failed_count"] += 1
        
        self.save()


class JobApplierGUI:
    """Main GUI application"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("Naukri Automation Suite")
        self.root.geometry("980x760")
        self.root.minsize(920, 700)

        # Apply a modern macOS-style theme
        self.configure_theme()
        
        # Initialize config and stats
        self.config = Config(CONFIG_FILE)
        self.stats = JobApplierStats(STATS_FILE)
        self.bot_stats = NaukriBotStats(BOT_STATS_FILE)
        self.linkedin_stats = JobApplierStats(LINKEDIN_STATS_FILE)  # Reuse JobApplierStats class
        
        # Process management
        self.process: Optional[subprocess.Popen] = None
        self.is_running = False
        self.log_thread: Optional[threading.Thread] = None
        self.stop_log_thread = False
        
        # Bot process management
        self.bot_process: Optional[subprocess.Popen] = None
        self.is_bot_running = False
        
        # LinkedIn process management
        self.linkedin_process: Optional[subprocess.Popen] = None
        self.is_linkedin_running = False

        # International Jobs process management
        self.intl_linkedin_process: Optional[subprocess.Popen] = None
        self.intl_indeed_process: Optional[subprocess.Popen] = None
        self.intl_reed_process: Optional[subprocess.Popen] = None
        self.intl_crawler_process: Optional[subprocess.Popen] = None
        self.is_intl_linkedin_running = False
        self.is_intl_indeed_running = False
        self.is_intl_reed_running = False
        self.is_intl_crawler_running = False

        # Thread-safe UI/log queues (Tk must only be touched from the main thread)
        self._ui_queue: "queue.Queue[tuple]" = queue.Queue()
        self._log_queue: "queue.Queue[str]" = queue.Queue()
        self._stop_ui_pump = False
        
        # Setup UI
        self.setup_ui()

        # Start the UI pump to process queued UI/log updates.
        self.root.after(50, self._pump_ui)
        
        # Start log monitoring
        self.start_log_monitoring()
        
        # Update stats display
        self.update_stats_display()
        self.update_bot_stats_display()
        self.update_linkedin_stats_display()
    
    def setup_ui(self):
        """Setup the user interface"""
        
        # Main container with padding
        main_frame = ttk.Frame(self.root, padding="14")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(2, weight=1)  # Notebook row
        
        # === Welcome Header ===
        header_frame = ttk.Frame(main_frame, padding="10")
        header_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))
        
        welcome_label = ttk.Label(header_frame, 
                                 text="Welcome to Naukri Automation Suite",
                                 style="Header.TLabel")
        welcome_label.pack()
        
        subtitle_label = ttk.Label(header_frame,
                                  text="Choose your automation tool below",
                                  style="Subtitle.TLabel")
        subtitle_label.pack(pady=(5, 0))

        ttk.Label(
            header_frame,
            text=f"Build: {APP_BUILD}",
            style="Muted.TLabel"
        ).pack(pady=(6, 0))
        
        # === Settings Button (Top Right) ===
        settings_frame = ttk.Frame(main_frame)
        settings_frame.grid(row=1, column=0, sticky=(tk.E), padx=10, pady=(0, 10))
        ttk.Button(
            settings_frame,
            text="Configure Credentials",
            command=self.show_settings,
            width=22
        ).pack()
        
        # === Tabbed Notebook ===
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=10, pady=(0, 10))
        
        # Create tabs
        job_applier_tab = ttk.Frame(self.notebook, padding="12")
        naukri_bot_tab = ttk.Frame(self.notebook, padding="12")
        linkedin_tab = ttk.Frame(self.notebook, padding="12")
        intl_jobs_tab = ttk.Frame(self.notebook, padding="12")
        
        self.notebook.add(job_applier_tab, text="Job Applier")
        self.notebook.add(naukri_bot_tab, text="Profile Updater")
        self.notebook.add(linkedin_tab, text="LinkedIn Applier")
        self.notebook.add(intl_jobs_tab, text="🌍 International Jobs")
        
        # === JOB APPLIER TAB ===
        self.setup_job_applier_tab(job_applier_tab)
        
        # === NAUKRI BOT TAB ===
        self.setup_naukri_bot_tab(naukri_bot_tab)
        
        # === LINKEDIN TAB ===
        self.setup_linkedin_tab(linkedin_tab)
        
        # === INTERNATIONAL JOBS TAB ===
        self.setup_intl_jobs_tab(intl_jobs_tab)
        
        # === SHARED LOG VIEWER ===
        log_frame = ttk.LabelFrame(
            main_frame,
            text="Activity Log",
            padding="12",
            style="Section.TLabelframe"
        )
        log_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=10, pady=(0, 10))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        # Log text area
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            height=15,
            font=self.fonts["fixed"],
            background=self.colors["surface"],
            foreground=self.colors["text"],
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=self.colors["border"]
        )
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Log controls
        log_controls = ttk.Frame(log_frame)
        log_controls.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(5, 0))
        
        self.auto_scroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(log_controls, text="Auto-scroll", variable=self.auto_scroll_var).pack(side=tk.LEFT)
        ttk.Button(log_controls, text="Clear Log", command=self.clear_log).pack(side=tk.LEFT, padx=5)
        ttk.Button(log_controls, text="Export Log", command=self.export_log).pack(side=tk.LEFT)
        ttk.Button(log_controls, text="View Full Log", command=self.view_full_log).pack(side=tk.LEFT, padx=5)
        
        # === Menu Bar ===
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Quit", command=self.quit_app, accelerator="Cmd+Q")
        
        # Settings menu
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_command(label="Configure Credentials...", command=self.show_settings)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.show_about)
        
        # Keyboard shortcuts
        self.root.bind('<Command-q>', lambda e: self.quit_app())

    def configure_theme(self):
        """Configure a modern macOS-inspired theme using ttk styles"""
        self.style = ttk.Style(self.root)
        # macOS: prefer native Aqua widgets; other platforms fall back to a theme we can style.
        themes = set(self.style.theme_names())
        if sys.platform == "darwin" and "aqua" in themes:
            self.style.theme_use("aqua")
        elif "clam" in themes:
            self.style.theme_use("clam")

        # Color palette
        self.colors = {
            "bg": "#f5f6f8",
            "surface": "#ffffff",
            "border": "#e3e5ea",
            "text": "#1f2933",
            "muted": "#6b7280",
            "accent": "#0a84ff",
            "accent_dark": "#006ad6",
            "success": "#2f9d50",
            "warning": "#c27c0e",
            "danger": "#d14343",
        }

        # Fonts
        preferred_font = "SF Pro Text" if "SF Pro Text" in tkfont.families() else None
        default_font = tkfont.nametofont("TkDefaultFont")
        text_font = tkfont.nametofont("TkTextFont")
        fixed_font = tkfont.nametofont("TkFixedFont")

        if preferred_font:
            default_font.configure(family=preferred_font, size=12)
            text_font.configure(family=preferred_font, size=12)
        else:
            default_font.configure(size=12)
            text_font.configure(size=12)

        fixed_font.configure(size=11)

        header_font = default_font.copy()
        header_font.configure(size=20, weight="bold")

        section_font = default_font.copy()
        section_font.configure(size=12, weight="bold")

        stat_font = default_font.copy()
        stat_font.configure(size=16, weight="bold")

        subtitle_font = default_font.copy()
        subtitle_font.configure(size=11)

        # Root background
        self.root.configure(bg=self.colors["bg"])

        # Global widget styles
        self.style.configure(
            "TFrame",
            background=self.colors["bg"],
        )
        self.style.configure(
            "Card.TFrame",
            background=self.colors["surface"],
        )
        self.style.configure(
            "TLabel",
            background=self.colors["bg"],
            foreground=self.colors["text"],
        )
        self.style.configure(
            "Header.TLabel",
            font=header_font,
            background=self.colors["bg"],
            foreground=self.colors["text"],
        )
        self.style.configure(
            "Subtitle.TLabel",
            font=subtitle_font,
            background=self.colors["bg"],
            foreground=self.colors["muted"],
        )
        self.style.configure(
            "Muted.TLabel",
            font=subtitle_font,
            background=self.colors["bg"],
            foreground=self.colors["muted"],
        )
        self.style.configure(
            "Section.TLabelframe",
            background=self.colors["surface"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
        )
        self.style.configure(
            "Section.TLabelframe.Label",
            font=section_font,
            background=self.colors["surface"],
            foreground=self.colors["text"],
        )
        self.style.configure(
            "SectionHeader.TLabel",
            font=section_font,
            background=self.colors["bg"],
            foreground=self.colors["text"],
        )
        self.style.configure(
            "StatValue.TLabel",
            font=stat_font,
            background=self.colors["surface"],
            foreground=self.colors["text"],
        )
        self.style.configure(
            "TButton",
            padding=(12, 6),
        )
        self.style.configure(
            "Primary.TButton",
            background=self.colors["accent"],
            foreground="#ffffff",
            padding=(14, 7),
        )
        self.style.map(
            "Primary.TButton",
            background=[
                ("active", self.colors["accent_dark"]),
                ("pressed", self.colors["accent_dark"]),
                ("disabled", "#c7d9f7"),
            ],
            foreground=[("disabled", "#f5f7fb")],
        )
        self.style.configure(
            "Danger.TButton",
            background=self.colors["danger"],
            foreground="#ffffff",
            padding=(14, 7),
        )
        self.style.map(
            "Danger.TButton",
            background=[
                ("active", "#b83838"),
                ("pressed", "#b83838"),
                ("disabled", "#f2c7c7"),
            ],
            foreground=[("disabled", "#fbf3f3")],
        )
        self.style.configure(
            "TEntry",
            padding=(10, 6),
        )
        self.style.configure(
            "TNotebook",
            background=self.colors["bg"],
            borderwidth=0,
        )
        self.style.configure(
            "TNotebook.Tab",
            padding=(14, 8),
        )

        # Keep references for use elsewhere
        self.fonts = {
            "fixed": fixed_font,
            "subtitle": subtitle_font,
        }

    def ui_call(self, func, *args, **kwargs):
        """Queue a UI update to be executed on the Tk main thread."""
        self._ui_queue.put((func, args, kwargs))

    def log_from_thread(self, text: str):
        """Queue log text from worker threads (no Tk calls here)."""
        self._log_queue.put(text)

    def _pump_ui(self):
        """Process queued UI/log updates. Runs on the Tk main thread."""
        if self._stop_ui_pump:
            return

        # 1) Apply UI actions
        for _ in range(200):
            try:
                func, args, kwargs = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                func(*args, **kwargs)
            except Exception:
                # Never let UI pump crash the app; log to stdout.
                print("UI action failed", file=sys.stderr)

        # 2) Append log chunks in a batch (much smoother than per-line inserts)
        log_chunks = []
        for _ in range(200):
            try:
                log_chunks.append(self._log_queue.get_nowait())
            except queue.Empty:
                break

        if log_chunks and hasattr(self, "log_text"):
            self.append_log("".join(log_chunks))

        self.root.after(50, self._pump_ui)
    
    def setup_job_applier_tab(self, parent):
        """Setup Job Applier tab content"""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        
        # Control Panel
        control_frame = ttk.LabelFrame(
            parent,
            text="Job Application Controls",
            padding="12",
            style="Section.TLabelframe"
        )
        control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        control_frame.columnconfigure(4, weight=1)
        
        # Row 1: Target Applications
        ttk.Label(control_frame, text="Target Applications:").grid(row=0, column=0, sticky=tk.W)
        self.target_var = tk.StringVar(value="30")
        ttk.Entry(control_frame, textvariable=self.target_var, width=10).grid(row=0, column=1, padx=5, sticky=tk.W)
        
        self.start_btn = ttk.Button(
            control_frame,
            text="Start Applying",
            command=self.start_applier,
            width=15,
            style="Primary.TButton"
        )
        self.start_btn.grid(row=0, column=2, padx=5)
        
        self.stop_btn = ttk.Button(
            control_frame,
            text="Stop",
            command=self.stop_applier,
            state=tk.DISABLED,
            width=12,
            style="Danger.TButton"
        )
        self.stop_btn.grid(row=0, column=3, padx=5)
        
        ttk.Label(control_frame, text="Status:").grid(row=0, column=4, padx=(20, 5), sticky=tk.E)
        self.status_var = tk.StringVar(value="Idle")
        self.status_label = ttk.Label(
            control_frame,
            textvariable=self.status_var,
            foreground=self.colors["muted"]
        )
        self.status_label.grid(row=0, column=5, sticky=tk.W)
        
        # Row 2: Job Titles
        ttk.Label(control_frame, text="Job Titles:").grid(row=1, column=0, sticky=tk.W, pady=(10, 0))
        self.job_titles_var = tk.StringVar(value=self.config.data.get("job_titles", "ML Engineer, AI Engineer, Software Engineer"))
        job_titles_entry = ttk.Entry(control_frame, textvariable=self.job_titles_var, width=70)
        job_titles_entry.grid(row=1, column=1, columnspan=4, padx=5, pady=(10, 0), sticky=(tk.W, tk.E))
        ttk.Label(control_frame, text="(comma-separated)", style="Muted.TLabel").grid(
            row=1, column=5, sticky=tk.W, pady=(10, 0))

        # Row 3: Headless toggle (prevents Chromium popups stealing focus)
        self.applier_headless_var = tk.BooleanVar(value=bool(self.config.data.get("ui_headless_naukri", True)))
        ttk.Checkbutton(
            control_frame,
            text="Run in background (no browser window)",
            variable=self.applier_headless_var
        ).grid(row=2, column=0, columnspan=6, sticky=tk.W, pady=(10, 0))
        
        # Statistics Panel
        stats_frame = ttk.LabelFrame(
            parent,
            text="Application Statistics",
            padding="12",
            style="Section.TLabelframe"
        )
        stats_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Stats labels
        ttk.Label(stats_frame, text="Today:").grid(row=0, column=0, sticky=tk.W)
        self.today_label = ttk.Label(stats_frame, text="0", style="StatValue.TLabel")
        self.today_label.grid(row=0, column=1, padx=10)
        
        ttk.Label(stats_frame, text="This Week:").grid(row=0, column=2, padx=(20, 0), sticky=tk.W)
        self.week_label = ttk.Label(stats_frame, text="0", style="StatValue.TLabel")
        self.week_label.grid(row=0, column=3, padx=10)
        
        ttk.Label(stats_frame, text="Total:").grid(row=0, column=4, padx=(20, 0), sticky=tk.W)
        self.total_label = ttk.Label(stats_frame, text="0", style="StatValue.TLabel")
        self.total_label.grid(row=0, column=5, padx=10)
        
        # Reset stats button
        ttk.Button(stats_frame, text="Reset Stats", command=self.reset_stats).grid(
            row=0, column=6, padx=(20, 0))
        
        # Scheduler Panel
        scheduler_frame = ttk.LabelFrame(
            parent,
            text="Automated Schedule",
            padding="12",
            style="Section.TLabelframe"
        )
        scheduler_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        scheduler_frame.columnconfigure(1, weight=1)
        
        ttk.Label(scheduler_frame, text="Scheduled Times:").grid(row=0, column=0, sticky=tk.W)
        self.schedule_text = tk.StringVar(value=self.get_schedule_display())
        ttk.Label(scheduler_frame, textvariable=self.schedule_text).grid(
            row=0, column=1, sticky=tk.W, padx=10
        )
        
        ttk.Button(scheduler_frame, text="Configure Schedule",
                  command=self.show_scheduler_config).grid(row=0, column=2, padx=5)
        
        self.scheduler_enabled_var = tk.BooleanVar(value=self.is_scheduler_installed())
        self.scheduler_toggle_btn = ttk.Button(scheduler_frame,
                                              text="Enable Scheduler" if not self.scheduler_enabled_var.get() else "Disable Scheduler",
                                              command=self.toggle_scheduler)
        self.scheduler_toggle_btn.grid(row=0, column=3, padx=5)
    
    def setup_naukri_bot_tab(self, parent):
        """Setup Naukri Bot tab content"""
        parent.columnconfigure(0, weight=1)
        
        # Control Panel
        control_frame = ttk.LabelFrame(
            parent,
            text="Profile Update Controls",
            padding="12",
            style="Section.TLabelframe"
        )
        control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Label(control_frame, text="Update your Naukri profile:").grid(row=0, column=0, sticky=tk.W)
        
        self.bot_start_btn = ttk.Button(
            control_frame,
            text="Start Profile Update",
            command=self.start_bot,
            width=20,
            style="Primary.TButton"
        )
        self.bot_start_btn.grid(row=0, column=1, padx=10)
        
        self.bot_stop_btn = ttk.Button(
            control_frame,
            text="Stop",
            command=self.stop_bot,
            state=tk.DISABLED,
            width=12,
            style="Danger.TButton"
        )
        self.bot_stop_btn.grid(row=0, column=2, padx=5)
        
        ttk.Label(control_frame, text="Status:").grid(row=0, column=3, padx=(20, 5))
        self.bot_status_var = tk.StringVar(value="Idle")
        self.bot_status_label = ttk.Label(
            control_frame,
            textvariable=self.bot_status_var,
            foreground=self.colors["muted"]
        )
        self.bot_status_label.grid(row=0, column=4)

        self.bot_headless_var = tk.BooleanVar(value=bool(self.config.data.get("ui_headless_bot", True)))
        ttk.Checkbutton(
            control_frame,
            text="Run in background (no browser window)",
            variable=self.bot_headless_var
        ).grid(row=1, column=0, columnspan=5, sticky=tk.W, pady=(10, 0))
        
        # Statistics Panel
        stats_frame = ttk.LabelFrame(
            parent,
            text="Update Statistics",
            padding="12",
            style="Section.TLabelframe"
        )
        stats_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Label(stats_frame, text="Last Run:").grid(row=0, column=0, sticky=tk.W)
        self.bot_last_run_label = ttk.Label(stats_frame, text="Never")
        self.bot_last_run_label.grid(row=0, column=1, padx=10)
        
        ttk.Label(stats_frame, text="Success:").grid(row=0, column=2, padx=(20, 0), sticky=tk.W)
        self.bot_success_label = ttk.Label(stats_frame, text="0", style="StatValue.TLabel")
        self.bot_success_label.grid(row=0, column=3, padx=10)
        
        ttk.Label(stats_frame, text="Failed:").grid(row=0, column=4, padx=(20, 0), sticky=tk.W)
        self.bot_failed_label = ttk.Label(stats_frame, text="0", style="StatValue.TLabel")
        self.bot_failed_label.grid(row=0, column=5, padx=10)
        
        ttk.Button(stats_frame, text="Reset Stats", command=self.reset_bot_stats).grid(
            row=0, column=6, padx=(20, 0))
        
        # Scheduler Panel
        scheduler_frame = ttk.LabelFrame(
            parent,
            text="Automated Schedule",
            padding="12",
            style="Section.TLabelframe"
        )
        scheduler_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        scheduler_frame.columnconfigure(1, weight=1)
        
        ttk.Label(scheduler_frame, text="Scheduled Times:").grid(row=0, column=0, sticky=tk.W)
        self.bot_schedule_text = tk.StringVar(value=self.get_bot_schedule_display())
        ttk.Label(scheduler_frame, textvariable=self.bot_schedule_text).grid(
            row=0, column=1, sticky=tk.W, padx=10
        )
        
        ttk.Button(scheduler_frame, text="Configure Schedule",
                  command=self.show_bot_scheduler_config).grid(row=0, column=2, padx=5)
        
        self.bot_scheduler_enabled_var = tk.BooleanVar(value=self.is_bot_scheduler_installed())
        self.bot_scheduler_toggle_btn = ttk.Button(scheduler_frame,
                                              text="Enable Scheduler" if not self.bot_scheduler_enabled_var.get() else "Disable Scheduler",
                                              command=self.toggle_bot_scheduler)
        self.bot_scheduler_toggle_btn.grid(row=0, column=3, padx=5)
    
    
    def setup_linkedin_tab(self, parent):
        """Setup LinkedIn Applier tab content"""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        
        # Control Panel
        control_frame = ttk.LabelFrame(
            parent,
            text="LinkedIn Job Application Controls",
            padding="12",
            style="Section.TLabelframe"
        )
        control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        control_frame.columnconfigure(4, weight=1)
        
        # Row 1: Target Applications
        ttk.Label(control_frame, text="Target Applications:").grid(row=0, column=0, sticky=tk.W)
        self.linkedin_target_var = tk.StringVar(value="30")
        ttk.Entry(control_frame, textvariable=self.linkedin_target_var, width=10).grid(row=0, column=1, padx=5, sticky=tk.W)
        
        self.linkedin_start_btn = ttk.Button(
            control_frame,
            text="Start LinkedIn Applying",
            command=self.start_linkedin_applier,
            width=20,
            style="Primary.TButton"
        )
        self.linkedin_start_btn.grid(row=0, column=2, padx=5)
        
        self.linkedin_stop_btn = ttk.Button(
            control_frame,
            text="Stop",
            command=self.stop_linkedin_applier,
            state=tk.DISABLED,
            width=12,
            style="Danger.TButton"
        )
        self.linkedin_stop_btn.grid(row=0, column=3, padx=5)
        
        ttk.Label(control_frame, text="Status:").grid(row=0, column=4, padx=(20, 5), sticky=tk.E)
        self.linkedin_status_var = tk.StringVar(value="Idle")
        self.linkedin_status_label = ttk.Label(
            control_frame,
            textvariable=self.linkedin_status_var,
            foreground=self.colors["muted"]
        )
        self.linkedin_status_label.grid(row=0, column=5, sticky=tk.W)
        
        # Row 2: Info
        ttk.Label(control_frame, text="Job Titles:", style="Muted.TLabel").grid(
            row=1, column=0, columnspan=6, sticky=tk.W, pady=(10, 0))
        ttk.Label(control_frame, text="Using shared job titles from settings", 
                 foreground=self.colors["accent"]).grid(row=2, column=0, columnspan=6, sticky=tk.W)

        self.linkedin_headless_var = tk.BooleanVar(value=bool(self.config.data.get("ui_headless_linkedin", True)))
        ttk.Checkbutton(
            control_frame,
            text="Run in background (no browser window)",
            variable=self.linkedin_headless_var
        ).grid(row=3, column=0, columnspan=6, sticky=tk.W, pady=(10, 0))
        
        # Statistics Panel
        stats_frame = ttk.LabelFrame(
            parent,
            text="LinkedIn Application Statistics",
            padding="12",
            style="Section.TLabelframe"
        )
        stats_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Label(stats_frame, text=" Today:").grid(row=0, column=0, sticky=tk.W)
        self.linkedin_today_label = ttk.Label(stats_frame, text="0", style="StatValue.TLabel")
        self.linkedin_today_label.grid(row=0, column=1, padx=10)
        
        ttk.Label(stats_frame, text="This Week:").grid(row=0, column=2, padx=(20, 0), sticky=tk.W)
        self.linkedin_week_label = ttk.Label(stats_frame, text="0", style="StatValue.TLabel")
        self.linkedin_week_label.grid(row=0, column=3, padx=10)
        
        ttk.Label(stats_frame, text="Total:").grid(row=0, column=4, padx=(20, 0), sticky=tk.W)
        self.linkedin_total_label = ttk.Label(stats_frame, text="0", style="StatValue.TLabel")
        self.linkedin_total_label.grid(row=0, column=5, padx=10)
        
        ttk.Button(stats_frame, text="Reset Stats", command=self.reset_linkedin_stats).grid(
            row=0, column=6, padx=(20, 0))
        
        # Scheduler Panel
        scheduler_frame = ttk.LabelFrame(
            parent,
            text="Automated Schedule",
            padding="12",
            style="Section.TLabelframe"
        )
        scheduler_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        scheduler_frame.columnconfigure(1, weight=1)
        
        ttk.Label(scheduler_frame, text="Scheduled Times:").grid(row=0, column=0, sticky=tk.W)
        self.linkedin_schedule_text = tk.StringVar(value=self.get_linkedin_schedule_display())
        ttk.Label(scheduler_frame, textvariable=self.linkedin_schedule_text).grid(
            row=0, column=1, sticky=tk.W, padx=10
        )
        
        ttk.Button(scheduler_frame, text="Configure Schedule",
                  command=self.show_linkedin_scheduler_config).grid(row=0, column=2, padx=5)
        
        self.linkedin_scheduler_enabled_var = tk.BooleanVar(value=self.is_linkedin_scheduler_installed())
        self.linkedin_scheduler_toggle_btn = ttk.Button(scheduler_frame,
                                              text="Enable Scheduler" if not self.linkedin_scheduler_enabled_var.get() else "Disable Scheduler",
                                              command=self.toggle_linkedin_scheduler)
        self.linkedin_scheduler_toggle_btn.grid(row=0, column=3, padx=5)

    def setup_intl_jobs_tab(self, parent):
        """Setup International Jobs Agent tab content"""
        parent.columnconfigure(0, weight=1)
        
        # 1. LinkedIn Agent Frame
        self._build_intl_agent_frame(
            parent, row=0, title="International LinkedIn Applier (Visa Sponsorship)",
            start_cmd=self.start_intl_linkedin, stop_cmd=self.stop_intl_linkedin,
            var_prefix="intl_linkedin"
        )
        
        # 2. Indeed Agent Frame
        self._build_intl_agent_frame(
            parent, row=1, title="International Indeed Applier",
            start_cmd=self.start_intl_indeed, stop_cmd=self.stop_intl_indeed,
            var_prefix="intl_indeed"
        )
        
        # 3. Reed Agent Frame
        self._build_intl_agent_frame(
            parent, row=2, title="International Reed.co.uk Applier",
            start_cmd=self.start_intl_reed, stop_cmd=self.stop_intl_reed,
            var_prefix="intl_reed"
        )
        
        # 4. Career Page Crawler Frame
        self._build_intl_agent_frame(
            parent, row=3, title="Internet-wide Career Page Crawler (Europe/Remote)",
            start_cmd=self.start_intl_crawler, stop_cmd=self.stop_intl_crawler,
            var_prefix="intl_crawler"
        )

        # Statistics Panel
        stats_frame = ttk.LabelFrame(parent, text="International Application Statistics", padding="12", style="Section.TLabelframe")
        stats_frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(10, 10))
        
        ttk.Label(stats_frame, text="Today:").grid(row=0, column=0, sticky=tk.W)
        self.intl_today_label = ttk.Label(stats_frame, text="0", style="StatValue.TLabel")
        self.intl_today_label.grid(row=0, column=1, padx=10)
        
        ttk.Label(stats_frame, text="Total:").grid(row=0, column=2, padx=(20, 0), sticky=tk.W)
        self.intl_total_label = ttk.Label(stats_frame, text="0", style="StatValue.TLabel")
        self.intl_total_label.grid(row=0, column=3, padx=10)
        
        ttk.Button(stats_frame, text="Reset Stats", command=self.reset_intl_stats).grid(row=0, column=4, padx=(20, 0))

    def _build_intl_agent_frame(self, parent, row, title, start_cmd, stop_cmd, var_prefix):
        frame = ttk.LabelFrame(parent, text=title, padding="10", style="Section.TLabelframe")
        frame.grid(row=row, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
        frame.columnconfigure(3, weight=1)
        
        ttk.Label(frame, text="Target:").grid(row=0, column=0, sticky=tk.W)
        target_var = tk.StringVar(value="15")
        setattr(self, f"{var_prefix}_target_var", target_var)
        ttk.Entry(frame, textvariable=target_var, width=5).grid(row=0, column=1, padx=5, sticky=tk.W)
        
        start_btn = ttk.Button(frame, text="Start", command=start_cmd, width=10, style="Primary.TButton")
        start_btn.grid(row=0, column=2, padx=5)
        setattr(self, f"{var_prefix}_start_btn", start_btn)
        
        stop_btn = ttk.Button(frame, text="Stop", command=stop_cmd, state=tk.DISABLED, width=10, style="Danger.TButton")
        stop_btn.grid(row=0, column=3, padx=5, sticky=tk.W)
        setattr(self, f"{var_prefix}_stop_btn", stop_btn)
        
        status_var = tk.StringVar(value="Idle")
        setattr(self, f"{var_prefix}_status_var", status_var)
        status_label = ttk.Label(frame, textvariable=status_var, foreground=self.colors["muted"])
        status_label.grid(row=0, column=4, sticky=tk.E)
        setattr(self, f"{var_prefix}_status_label", status_label)
        
        headless_var = tk.BooleanVar(value=True)
        setattr(self, f"{var_prefix}_headless_var", headless_var)
        ttk.Checkbutton(frame, text="Headless", variable=headless_var).grid(row=0, column=5, padx=10, sticky=tk.E)

    def _run_intl_agent(self, script, var_prefix):
        if getattr(self, f"is_{var_prefix}_running"): return
        
        target = getattr(self, f"{var_prefix}_target_var").get()
        headless = getattr(self, f"{var_prefix}_headless_var").get()
        
        cmd = [sys.executable, "-u", str(script), "--target", str(target)]
        if headless: cmd.append("--headless")
        
        self.log_from_thread(f"[{var_prefix}] Starting: target={target}, headless={headless}\n")
        
        def run_proc():
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, cwd=str(SCRIPT_DIR))
                setattr(self, f"{var_prefix}_process", proc)
                setattr(self, f"is_{var_prefix}_running", True)
                self.ui_call(lambda: self._update_intl_ui(var_prefix, True))
                
                for line in proc.stdout:
                    self.log_from_thread(f"[{var_prefix}] {line}")
                
                proc.wait()
                setattr(self, f"is_{var_prefix}_running", False)
                self.ui_call(lambda: self._update_intl_ui(var_prefix, False))
                self.log_from_thread(f"[{var_prefix}] Finished.\n")
            except Exception as e:
                setattr(self, f"is_{var_prefix}_running", False)
                self.ui_call(lambda: self._update_intl_ui(var_prefix, False))
                self.log_from_thread(f"[{var_prefix}] Error: {e}\n")
        
        threading.Thread(target=run_proc, daemon=True).start()

    def _stop_intl_agent(self, var_prefix):
        proc = getattr(self, f"{var_prefix}_process", None)
        if proc and proc.poll() is None:
            proc.terminate()
            self.log_from_thread(f"[{var_prefix}] Stopped by user.\n")

    def _update_intl_ui(self, var_prefix, running):
        getattr(self, f"{var_prefix}_start_btn").configure(state=tk.DISABLED if running else tk.NORMAL)
        getattr(self, f"{var_prefix}_stop_btn").configure(state=tk.NORMAL if running else tk.DISABLED)
        getattr(self, f"{var_prefix}_status_var").set("Running..." if running else "Idle")
        getattr(self, f"{var_prefix}_status_label").configure(foreground=self.colors["success"] if running else self.colors["muted"])
        self.update_intl_stats_display()

    def start_intl_linkedin(self): self._run_intl_agent(INTL_LINKEDIN_SCRIPT, "intl_linkedin")
    def stop_intl_linkedin(self): self._stop_intl_agent("intl_linkedin")
    def start_intl_indeed(self): self._run_intl_agent(INTL_INDEED_SCRIPT, "intl_indeed")
    def stop_intl_indeed(self): self._stop_intl_agent("intl_indeed")
    def start_intl_reed(self): self._run_intl_agent(INTL_REED_SCRIPT, "intl_reed")
    def stop_intl_reed(self): self._stop_intl_agent("intl_reed")
    def start_intl_crawler(self): self._run_intl_agent(INTL_CRAWLER_SCRIPT, "intl_crawler")
    def stop_intl_crawler(self): self._stop_intl_agent("intl_crawler")

    def update_intl_stats_display(self):
        try:
            if INTL_STATS_FILE.exists():
                with open(INTL_STATS_FILE, 'r') as f: stats = json.load(f)
                self.intl_today_label.configure(text=str(stats.get("today_count", 0)))
                self.intl_total_label.configure(text=str(stats.get("total_applications", 0)))
        except: pass

    def reset_intl_stats(self):
        if messagebox.askyesno("Reset Stats", "Reset International Jobs statistics?"):
            try:
                with open(INTL_STATS_FILE, 'w') as f: json.dump({"total_applications": 0, "today_count": 0, "last_run": None, "success_count": 0, "daily_history": {}, "by_source": {}}, f, indent=2)
                self.update_intl_stats_display()
            except: pass


    def setup_shared_log_viewer(self):
        """Setup the shared log viewer section"""
        log_frame = ttk.LabelFrame(main_frame, text="Application Log", padding="10")
        log_frame.grid(row=6, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        # Log text area
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            height=20,
            font=self.fonts["fixed"],
            background=self.colors["surface"],
            foreground=self.colors["text"],
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=self.colors["border"]
        )
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Log controls
        log_controls = ttk.Frame(log_frame)
        log_controls.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(5, 0))
        
        self.auto_scroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(log_controls, text="Auto-scroll", 
                       variable=self.auto_scroll_var).pack(side=tk.LEFT)
        
        ttk.Button(log_controls, text="Clear Log", 
                  command=self.clear_log).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(log_controls, text="Export Log", 
                  command=self.export_log).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(log_controls, text="View Full Log", 
                  command=self.view_full_log).pack(side=tk.LEFT, padx=5)
        
        # === Menu Bar ===
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Quit", command=self.quit_app, accelerator="Cmd+Q")
        
        # Settings menu
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_command(label="Configure Credentials...", command=self.show_settings)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.show_about)
        
        # Keyboard shortcuts
        self.root.bind('<Command-q>', lambda e: self.quit_app())
    
    def show_settings(self):
        """Show settings dialog"""
        # Create settings window
        settings_win = tk.Toplevel(self.root)
        settings_win.title("Settings")
        settings_win.geometry("680x720")
        settings_win.transient(self.root)
        settings_win.grab_set()
        settings_win.configure(bg=self.colors["bg"])
        
        # Center the window
        settings_win.update_idletasks()
        x = (settings_win.winfo_screenwidth() // 2) - (680 // 2)
        y = (settings_win.winfo_screenheight() // 2) - (720 // 2)
        settings_win.geometry(f"680x720+{x}+{y}")
        
        # Main frame
        main = ttk.Frame(settings_win, padding="24")
        main.pack(fill=tk.BOTH, expand=True)
        
        # Email
        ttk.Label(main, text="Naukri Email:", style="SectionHeader.TLabel").grid(
            row=0, column=0, sticky=tk.W, pady=(0, 5))
        email_var = tk.StringVar(value=self.config.data.get("email", ""))
        email_entry = ttk.Entry(main, textvariable=email_var, width=40)
        email_entry.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
        
        # Password
        ttk.Label(main, text="Naukri Password:", style="SectionHeader.TLabel").grid(
            row=2, column=0, sticky=tk.W, pady=(0, 5))
        password_var = tk.StringVar(value=self.config.data.get("password", ""))
        password_entry = ttk.Entry(main, textvariable=password_var, width=40, show="•")
        password_entry.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
        
        # === LINKEDIN CREDENTIALS ===
        ttk.Label(main, text="LinkedIn Credentials", style="SectionHeader.TLabel").grid(
            row=4, column=0, sticky=tk.W, pady=(10, 10))
        
        # LinkedIn Email
        ttk.Label(main, text="LinkedIn Email:", style="SectionHeader.TLabel").grid(
            row=5, column=0, sticky=tk.W, pady=(0, 5))
        linkedin_email_var = tk.StringVar(value=self.config.data.get("linkedin_email", ""))
        linkedin_email_entry = ttk.Entry(main, textvariable=linkedin_email_var, width=40)
        linkedin_email_entry.grid(row=6, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
        
        # LinkedIn Password
        ttk.Label(main, text="LinkedIn Password:", style="SectionHeader.TLabel").grid(
            row=7, column=0, sticky=tk.W, pady=(0, 5))
        linkedin_password_var = tk.StringVar(value=self.config.data.get("linkedin_password", ""))
        linkedin_password_entry = ttk.Entry(main, textvariable=linkedin_password_var, width=40, show="•")
        linkedin_password_entry.grid(row=8, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
        
        # LinkedIn Phone
        ttk.Label(main, text="LinkedIn Phone (for applications):", style="SectionHeader.TLabel").grid(
            row=9, column=0, sticky=tk.W, pady=(0, 5))
        linkedin_phone_var = tk.StringVar(value=self.config.data.get("linkedin_phone", ""))
        linkedin_phone_entry = ttk.Entry(main, textvariable=linkedin_phone_var, width=40)
        linkedin_phone_entry.grid(row=10, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
        
        # Resume path
        ttk.Label(main, text="Resume Path:", style="SectionHeader.TLabel").grid(
            row=11, column=0, sticky=tk.W, pady=(0, 5))
        
        resume_frame = ttk.Frame(main)
        resume_frame.grid(row=12, column=0, sticky=(tk.W, tk.E), pady=(0, 20))
        resume_frame.columnconfigure(0, weight=1)
        
        resume_var = tk.StringVar(value=self.config.data.get("resume_path", ""))
        resume_entry = ttk.Entry(resume_frame, textvariable=resume_var)
        resume_entry.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
        
        def browse_resume():
            filename = filedialog.askopenfilename(
                title="Select Resume",
                filetypes=[("PDF files", "*.pdf"), ("Word files", "*.doc *.docx"), ("All files", "*.*")]
            )
            if filename:
                resume_var.set(filename)
        
        ttk.Button(resume_frame, text="Browse...", command=browse_resume).grid(row=0, column=1)
        
        # Job Titles
        ttk.Label(main, text="Job Titles (comma-separated):", style="SectionHeader.TLabel").grid(
            row=13, column=0, sticky=tk.W, pady=(0, 5)
        )
        job_titles_var = tk.StringVar(value=self.config.data.get("job_titles", "ML Engineer, AI Engineer, Software Engineer"))
        job_titles_entry = ttk.Entry(main, textvariable=job_titles_var, width=50)
        job_titles_entry.grid(row=14, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
        
        # Buttons
        button_frame = ttk.Frame(main)
        button_frame.grid(row=15, column=0, sticky=(tk.E))
        
        def save_settings():
            # Validate
            if not email_var.get() or not password_var.get():
                messagebox.showerror("Error", "Email and password are required!")
                return
            
            # Save to config
            self.config.data["email"] = email_var.get()
            self.config.data["password"] = password_var.get()
            self.config.data["resume_path"] = resume_var.get()
            self.config.data["job_titles"] = job_titles_var.get()
            self.config.data["linkedin_email"] = linkedin_email_var.get()
            self.config.data["linkedin_password"] = linkedin_password_var.get()
            self.config.data["linkedin_phone"] = linkedin_phone_var.get()
            self.config.save()
            
            # Also update .env file for compatibility
            env_path = SCRIPT_DIR / ".env"
            with open(env_path, 'w') as f:
                f.write(f"NAUKRI_EMAIL={email_var.get()}\n")
                f.write(f"NAUKRI_PASSWORD={password_var.get()}\n")
                f.write(f"RESUME_PATH={resume_var.get()}\n")
                f.write(f"JOB_TITLES={job_titles_var.get()}\n")
                f.write(f"LINKEDIN_EMAIL={linkedin_email_var.get()}\n")
                f.write(f"LINKEDIN_PASSWORD={linkedin_password_var.get()}\n")
                f.write(f"LINKEDIN_PHONE={linkedin_phone_var.get()}\n")

            
            messagebox.showinfo("Success", "Settings saved successfully!")
            settings_win.destroy()
        
        ttk.Button(button_frame, text="Save", command=save_settings).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=settings_win.destroy).pack(side=tk.RIGHT)
        
        main.columnconfigure(0, weight=1)
    
    def get_schedule_display(self) -> str:
        """Get formatted schedule times for display"""
        times = self.config.data.get("schedule_times", [])
        if not times:
            return "None"
        return ", ".join(times)
    
    def is_scheduler_installed(self) -> bool:
        """Check if cron jobs are installed"""
        try:
            result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
            return 'job_applier.py' in result.stdout
        except:
            return False
    
    def show_scheduler_config(self):
        """Show scheduler configuration dialog"""
        # Create scheduler window
        sched_win = tk.Toplevel(self.root)
        sched_win.title("Configure Schedule")
        sched_win.geometry("440x380")
        sched_win.transient(self.root)
        sched_win.grab_set()
        sched_win.configure(bg=self.colors["bg"])
        
        # Center the window
        sched_win.update_idletasks()
        x = (sched_win.winfo_screenwidth() // 2) - (440 // 2)
        y = (sched_win.winfo_screenheight() // 2) - (380 // 2)
        sched_win.geometry(f"440x380+{x}+{y}")
        
        # Main frame
        main = ttk.Frame(sched_win, padding="20")
        main.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main, text="Scheduled Run Times", style="SectionHeader.TLabel").pack(pady=(0, 10))
        
        ttk.Label(main, text="The job applier will run automatically at these times each day:",
                 wraplength=380, style="Muted.TLabel").pack(pady=(0, 10))
        
        # Listbox for times
        list_frame = ttk.Frame(main)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        times_list = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            height=8,
            background=self.colors["surface"],
            foreground=self.colors["text"],
            selectbackground=self.colors["accent"],
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            borderwidth=0
        )
        times_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=times_list.yview)
        
        # Populate current times
        current_times = self.config.data.get("schedule_times", [])
        for time in current_times:
            times_list.insert(tk.END, time)
        
        # Add/Remove controls
        control_frame = ttk.Frame(main)
        control_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(control_frame, text="Add time (HH:MM):").pack(side=tk.LEFT)
        time_var = tk.StringVar(value="09:00")
        time_entry = ttk.Entry(control_frame, textvariable=time_var, width=10)
        time_entry.pack(side=tk.LEFT, padx=5)
        
        def add_time():
            time_str = time_var.get()
            # Validate format
            try:
                hour, minute = map(int, time_str.split(':'))
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    formatted = f"{hour:02d}:{minute:02d}"
                    if formatted not in times_list.get(0, tk.END):
                        times_list.insert(tk.END, formatted)
                else:
                    raise ValueError
            except:
                messagebox.showerror("Invalid Time", "Please use HH:MM format (00:00 to 23:59)")
        
        ttk.Button(control_frame, text="Add", command=add_time).pack(side=tk.LEFT)
        
        def remove_time():
            selection = times_list.curselection()
            if selection:
                times_list.delete(selection[0])
        
        ttk.Button(control_frame, text="Remove Selected", command=remove_time).pack(side=tk.LEFT, padx=5)
        
        # Buttons
        button_frame = ttk.Frame(main)
        button_frame.pack(fill=tk.X)
        
        def save_schedule():
            # Get all times from listbox
            times = list(times_list.get(0, tk.END))
            
            # Save to config
            self.config.data["schedule_times"] = times
            self.config.save()
            
            # Update display
            self.schedule_text.set(self.get_schedule_display())
            
            # If scheduler is enabled, update cron jobs
            if self.scheduler_enabled_var.get():
                self.install_scheduler()
                messagebox.showinfo("Success", "Schedule updated and applied to cron!")
            else:
                messagebox.showinfo("Success", "Schedule saved! Enable the scheduler to apply changes.")
            
            sched_win.destroy()
        
        ttk.Button(button_frame, text="Save", command=save_schedule).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=sched_win.destroy).pack(side=tk.RIGHT)
    
    def toggle_scheduler(self):
        """Enable or disable the scheduler"""
        if self.scheduler_enabled_var.get():
            # Disable
            self.uninstall_scheduler()
        else:
            # Enable
            self.install_scheduler()
    
    def install_scheduler(self):
        """Install cron jobs for scheduled times"""
        try:
            times = self.config.data.get("schedule_times", [])
            if not times:
                messagebox.showwarning("No Schedule", "Please configure at least one scheduled time first.")
                return
            
            # Get current crontab
            try:
                result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
                current_cron = result.stdout
            except:
                current_cron = ""
            
            # Remove existing job_applier entries
            lines = [line for line in current_cron.split('\n') if 'job_applier.py' not in line]
            
            # Add new entries
            for time_str in times:
                hour, minute = time_str.split(':')
                cron_line = f"{minute} {hour} * * * cd {SCRIPT_DIR} && {sys.executable} {APPLIER_SCRIPT} --target 30 --headless >> {LOG_FILE} 2>&1"
                lines.append(cron_line)
            
            # Write new crontab
            new_cron = '\n'.join(lines) + '\n'
            process = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE, text=True)
            process.communicate(input=new_cron)
            
            if process.returncode == 0:
                self.scheduler_enabled_var.set(True)
                self.scheduler_toggle_btn.config(text="Disable Scheduler")
                messagebox.showinfo("Success", f"Scheduler enabled! Jobs will run at: {self.get_schedule_display()}")
            else:
                messagebox.showerror("Error", "Failed to install cron jobs")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to install scheduler: {str(e)}")
    
    def uninstall_scheduler(self):
        """Remove cron jobs"""
        try:
            # Get current crontab
            result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
            current_cron = result.stdout
            
            # Remove job_applier entries
            lines = [line for line in current_cron.split('\n') if 'job_applier.py' not in line]
            
            # Write new crontab
            new_cron = '\n'.join(lines) + '\n'
            process = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE, text=True)
            process.communicate(input=new_cron)
            
            if process.returncode == 0:
                self.scheduler_enabled_var.set(False)
                self.scheduler_toggle_btn.config(text="Enable Scheduler")
                messagebox.showinfo("Success", "Scheduler disabled!")
            else:
                messagebox.showerror("Error", "Failed to remove cron jobs")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to uninstall scheduler: {str(e)}")
    
    def start_applier(self):
        """Start the job applier"""
        if self.is_running:
            return
        
        try:
            target = int(self.target_var.get())
            if target <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid positive number for target applications.")
            return
        
        # Snapshot any Tk variables on the main thread (Tk is not thread-safe)
        job_titles = self.job_titles_var.get().strip() if hasattr(self, "job_titles_var") else ""

        # Persist job titles immediately so scheduled/background runs stay in sync
        self.config.data["job_titles"] = job_titles
        self.config.save()

        # Update UI
        self.is_running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.update_status("Running", "blue")
        
        # Add log entry
        self.append_log(f"\n{'='*60}\n")
        self.append_log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting job applier...\n")
        self.append_log(f"Target: {target} applications\n")
        if hasattr(self, "applier_headless_var") and self.applier_headless_var.get():
            self.append_log("Mode: Background (headless)\n")
        else:
            self.append_log("Mode: Visible browser\n")
        self.append_log(f"{'='*60}\n\n")
        
        # Start process in thread
        headless_var = getattr(self, "applier_headless_var", None)
        headless = bool(headless_var.get()) if headless_var is not None else True
        self.config.data["ui_headless_naukri"] = headless
        self.config.save()
        threading.Thread(target=self.run_applier, args=(target, headless, job_titles), daemon=True).start()
    
    def run_applier(self, target: int, headless: bool, job_titles: str):
        """Run the job applier process"""
        try:
            # Build command
            cmd = [sys.executable, str(APPLIER_SCRIPT), "--target", str(target)]
            if headless:
                cmd.append("--headless")
            
            # Add job titles if provided
            if job_titles:
                cmd.extend(["--job-titles", job_titles])
                self.log_from_thread(f"Using job titles: {job_titles}\n")
            
            # Start process
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                cwd=str(SCRIPT_DIR)
            )
            
            # Read output
            for line in self.process.stdout:
                if not self.is_running:
                    break
                self.log_from_thread(line)
            
            # Wait for completion
            self.process.wait()
            
            # Check result
            if self.process.returncode == 0:
                self.log_from_thread("\n✓ Job application completed successfully!\n")
                self.ui_call(self.update_status, "Completed", "green")
                # Update stats (parse from log for actual count, using target as estimate)
                self.stats.update_today(target)
                self.ui_call(self.update_stats_display)
            else:
                self.log_from_thread(f"\n✗ Job application failed with code {self.process.returncode}\n")
                self.ui_call(self.update_status, "Failed", "red")
            
        except Exception as e:
            self.log_from_thread(f"\n✗ Error: {str(e)}\n")
            self.ui_call(self.update_status, "Error", "red")
        finally:
            self.process = None
            self.is_running = False
            self.ui_call(self.reset_buttons)
    
    def stop_applier(self):
        """Stop the running job applier"""
        if self.process and self.is_running:
            self.is_running = False
            self.process.terminate()
            self.append_log(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Stopping...\n")
            self.update_status("Stopped", "orange")
            self.reset_buttons()
    
    def reset_buttons(self):
        """Reset button states"""
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        if not self.is_running:
            self.update_status("Idle", "gray")
    
    def update_status(self, status: str, color: str):
        """Update status display"""
        self.status_var.set(status)
        self.status_label.config(foreground=color)
    
    def append_log(self, text: str):
        """Append text to log viewer"""
        self.log_text.insert(tk.END, text)
        if self.auto_scroll_var.get():
            self.log_text.see(tk.END)
    
    def clear_log(self):
        """Clear the log viewer"""
        self.log_text.delete(1.0, tk.END)
    
    def export_log(self):
        """Export log to file"""
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile=f"naukri_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        
        if filename:
            try:
                with open(filename, 'w') as f:
                    f.write(self.log_text.get(1.0, tk.END))
                messagebox.showinfo("Success", f"Log exported to:\n{filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export log:\n{str(e)}")
    
    def view_full_log(self):
        """Open the full log file"""
        if LOG_FILE.exists():
            subprocess.run(['open', '-a', 'Console', str(LOG_FILE)])
        else:
            messagebox.showinfo("No Log File", "No log file found yet.")
    
    def start_log_monitoring(self):
        """Start monitoring the log file for updates"""
        self.log_thread = threading.Thread(target=self.monitor_log_file, daemon=True)
        self.log_thread.start()
    
    def monitor_log_file(self):
        """Monitor log file for new entries"""
        last_size = 0
        
        while not self.stop_log_thread:
            try:
                if LOG_FILE.exists() and self.is_running:
                    current_size = LOG_FILE.stat().st_size
                    if current_size > last_size:
                        with open(LOG_FILE, 'r') as f:
                            f.seek(last_size)
                            new_content = f.read()
                            if new_content:
                                self.log_from_thread(new_content)
                        last_size = current_size
            except:
                pass
            
            threading.Event().wait(0.5)
    
    def update_stats_display(self):
        """Update statistics display"""
        self.today_label.config(text=str(self.stats.data["today_count"]))
        self.week_label.config(text=str(self.stats.get_week_total()))
        self.total_label.config(text=str(self.stats.data["total_applications"]))
    
    def reset_stats(self):
        """Reset all statistics"""
        if messagebox.askyesno("Reset Statistics", 
                              "Are you sure you want to reset all statistics?"):
            self.stats.data = {
                "total_applications": 0,
                "today_count": 0,
                "last_run": None,
                "success_count": 0,
                "daily_history": {}
            }
            self.stats.save()
            self.update_stats_display()
    
    def show_about(self):
        """Show about dialog"""
        messagebox.showinfo(
            "About Naukri Job Applier",
            "Naukri Job Applier v1.0\n\n"
            "Automated job application bot for Naukri.com\n\n"
            "Features:\n"
            "• Automated job applications\n"
            "• Smart filtering (experience, salary)\n"
            "• Intelligent chatbot responses\n"
            "• Scheduled runs (9 AM, 7 PM)\n"
            "• Application statistics tracking\n\n"
            f"Build: {APP_BUILD}\n"
            f"GUI Path: {Path(__file__).resolve()}\n\n"
            "© 2026"
        )
    
    # ========== Naukri Bot Methods ==========
    
    def start_bot(self):
        """Start the naukri bot"""
        if self.is_bot_running:
            return
        
        # Update UI
        self.is_bot_running = True
        self.bot_start_btn.config(state=tk.DISABLED)
        self.bot_stop_btn.config(state=tk.NORMAL)
        self.update_bot_status("Running", "blue")
        
        # Add log entry
        self.append_log(f"\n{'='*60}\n")
        self.append_log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting Naukri Bot...\n")
        if hasattr(self, "bot_headless_var") and self.bot_headless_var.get():
            self.append_log("Mode: Background (headless)\n")
        else:
            self.append_log("Mode: Visible browser\n")
        self.append_log(f"{'='*60}\n\n")
        
        # Start process in thread
        headless_var = getattr(self, "bot_headless_var", None)
        headless = bool(headless_var.get()) if headless_var is not None else True
        self.config.data["ui_headless_bot"] = headless
        self.config.save()
        threading.Thread(target=self.run_bot, args=(headless,), daemon=True).start()
    
    def run_bot(self, headless: bool):
        """Run the naukri bot process"""
        try:
            # Build command
            cmd = [sys.executable, str(BOT_SCRIPT)]
            if headless:
                cmd.append("--headless")
            
            # Start process
            self.bot_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                cwd=str(SCRIPT_DIR)
            )
            
            # Read output
            for line in self.bot_process.stdout:
                if not self.is_bot_running:
                    break
                self.log_from_thread(f"[BOT] {line}")
            
            # Wait for completion
            self.bot_process.wait()
            
            # Check result
            if self.bot_process.returncode == 0:
                self.log_from_thread("\n✓ Naukri Bot completed successfully!\n")
                self.ui_call(self.update_bot_status, "Completed", "green")
                self.bot_stats.update_run(success=True)
            else:
                self.log_from_thread(f"\n✗ Naukri Bot failed with code {self.bot_process.returncode}\n")
                self.ui_call(self.update_bot_status, "Failed", "red")
                self.bot_stats.update_run(success=False)
            
            self.ui_call(self.update_bot_stats_display)
            
        except Exception as e:
            self.log_from_thread(f"\n✗ Bot Error: {str(e)}\n")
            self.ui_call(self.update_bot_status, "Error", "red")
            self.bot_stats.update_run(success=False)
            self.ui_call(self.update_bot_stats_display)
        finally:
            self.bot_process = None
            self.is_bot_running = False
            self.ui_call(self.reset_bot_buttons)
    
    def stop_bot(self):
        """Stop the running naukri bot"""
        if self.bot_process and self.is_bot_running:
            self.is_bot_running = False
            self.bot_process.terminate()
            self.append_log(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Stopping Bot...\n")
            self.update_bot_status("Stopped", "orange")
            self.reset_bot_buttons()
    
    def reset_bot_buttons(self):
        """Reset bot button states"""
        self.bot_start_btn.config(state=tk.NORMAL)
        self.bot_stop_btn.config(state=tk.DISABLED)
        if not self.is_bot_running:
            self.update_bot_status("Idle", "gray")
    
    def update_bot_status(self, status: str, color: str):
        """Update bot status display"""
        self.bot_status_var.set(status)
        self.bot_status_label.config(foreground=color)
    
    def update_bot_stats_display(self):
        """Update bot statistics display"""
        last_run = self.bot_stats.data.get("last_run")
        if last_run:
            try:
                dt = datetime.fromisoformat(last_run)
                formatted = dt.strftime("%Y-%m-%d %H:%M")
            except:
                formatted = "Unknown"
        else:
            formatted = "Never"
        
        self.bot_last_run_label.config(text=formatted)
        self.bot_success_label.config(text=str(self.bot_stats.data["success_count"]))
        self.bot_failed_label.config(text=str(self.bot_stats.data["failed_count"]))
    
    def reset_bot_stats(self):
        """Reset bot statistics"""
        if messagebox.askyesno("Reset Bot Statistics", 
                              "Are you sure you want to reset bot statistics?"):
            self.bot_stats.data = {
                "last_run": None,
                "success_count": 0,
                "failed_count": 0,
                "total_runs": 0
            }
            self.bot_stats.save()
            self.update_bot_stats_display()
    
    def get_bot_schedule_display(self) -> str:
        """Get formatted bot schedule times for display"""
        times = self.config.data.get("bot_schedule_times", [])
        if not times:
            return "None"
        return ", ".join(times)
    
    def is_bot_scheduler_installed(self) -> bool:
        """Check if bot cron jobs are installed"""
        try:
            result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
            return 'naukri_bot.py' in result.stdout
        except:
            return False
    
    def show_bot_scheduler_config(self):
        """Show bot scheduler configuration dialog"""
        sched_win = tk.Toplevel(self.root)
        sched_win.title("Configure Bot Schedule")
        sched_win.geometry("440x380")
        sched_win.transient(self.root)
        sched_win.grab_set()
        sched_win.configure(bg=self.colors["bg"])
        
        sched_win.update_idletasks()
        x = (sched_win.winfo_screenwidth() // 2) - (440 // 2)
        y = (sched_win.winfo_screenheight() // 2) - (380 // 2)
        sched_win.geometry(f"440x380+{x}+{y}")
        
        main = ttk.Frame(sched_win, padding="20")
        main.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main, text="Bot Scheduled Run Times", style="SectionHeader.TLabel").pack(pady=(0, 10))
        ttk.Label(main, text="The profile update bot will run automatically at these times each day:",
                 wraplength=380, style="Muted.TLabel").pack(pady=(0, 10))
        
        list_frame = ttk.Frame(main)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        times_list = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            height=8,
            background=self.colors["surface"],
            foreground=self.colors["text"],
            selectbackground=self.colors["accent"],
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            borderwidth=0
        )
        times_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=times_list.yview)
        
        current_times = self.config.data.get("bot_schedule_times", [])
        for time in current_times:
            times_list.insert(tk.END, time)
        
        control_frame = ttk.Frame(main)
        control_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(control_frame, text="Add time (HH:MM):").pack(side=tk.LEFT)
        time_var = tk.StringVar(value="09:00")
        time_entry = ttk.Entry(control_frame, textvariable=time_var, width=10)
        time_entry.pack(side=tk.LEFT, padx=5)
        
        def add_time():
            time_str = time_var.get()
            try:
                hour, minute = map(int, time_str.split(':'))
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    formatted = f"{hour:02d}:{minute:02d}"
                    if formatted not in times_list.get(0, tk.END):
                        times_list.insert(tk.END, formatted)
                else:
                    raise ValueError
            except:
                messagebox.showerror("Invalid Time", "Please use HH:MM format (00:00 to 23:59)")
        
        ttk.Button(control_frame, text="Add", command=add_time).pack(side=tk.LEFT)
        
        def remove_time():
            selection = times_list.curselection()
            if selection:
                times_list.delete(selection[0])
        
        ttk.Button(control_frame, text="Remove Selected", command=remove_time).pack(side=tk.LEFT, padx=5)
        
        button_frame = ttk.Frame(main)
        button_frame.pack(fill=tk.X)
        
        def save_schedule():
            times = list(times_list.get(0, tk.END))
            self.config.data["bot_schedule_times"] = times
            self.config.save()
            self.bot_schedule_text.set(self.get_bot_schedule_display())
            
            if self.bot_scheduler_enabled_var.get():
                self.install_bot_scheduler()
                messagebox.showinfo("Success", "Bot schedule updated and applied to cron!")
            else:
                messagebox.showinfo("Success", "Bot schedule saved! Enable the scheduler to apply changes.")
            
            sched_win.destroy()
        
        ttk.Button(button_frame, text="Save", command=save_schedule).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=sched_win.destroy).pack(side=tk.RIGHT)
    
    def toggle_bot_scheduler(self):
        """Enable or disable the bot scheduler"""
        if self.bot_scheduler_enabled_var.get():
            self.uninstall_bot_scheduler()
        else:
            self.install_bot_scheduler()
    
    def install_bot_scheduler(self):
        """Install cron jobs for bot scheduled times"""
        try:
            times = self.config.data.get("bot_schedule_times", [])
            if not times:
                messagebox.showwarning("No Schedule", "Please configure at least one scheduled time first.")
                return
            
            try:
                result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
                current_cron = result.stdout
            except:
                current_cron = ""
            
            lines = [line for line in current_cron.split('\n') if 'naukri_bot.py' not in line]
            
            bot_log_file = LOG_DIR / "naukri_bot.log"
            for time_str in times:
                hour, minute = time_str.split(':')
                cron_line = f"{minute} {hour} * * * cd {SCRIPT_DIR} && {sys.executable} {BOT_SCRIPT} --headless >> {bot_log_file} 2>&1"
                lines.append(cron_line)
            
            new_cron = '\n'.join(lines) + '\n'
            process = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE, text=True)
            process.communicate(input=new_cron)
            
            if process.returncode == 0:
                self.bot_scheduler_enabled_var.set(True)
                self.bot_scheduler_toggle_btn.config(text="Disable Scheduler")
                messagebox.showinfo("Success", f"Bot scheduler enabled! Bot will run at: {self.get_bot_schedule_display()}")
            else:
                messagebox.showerror("Error", "Failed to install bot cron jobs")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to install bot scheduler: {str(e)}")
    
    def uninstall_bot_scheduler(self):
        """Remove bot cron jobs"""
        try:
            result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
            current_cron = result.stdout
            
            lines = [line for line in current_cron.split('\n') if 'naukri_bot.py' not in line]
            
            new_cron = '\n'.join(lines) + '\n'
            process = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE, text=True)
            process.communicate(input=new_cron)
            
            if process.returncode == 0:
                self.bot_scheduler_enabled_var.set(False)
                self.bot_scheduler_toggle_btn.config(text="Enable Scheduler")
                messagebox.showinfo("Success", "Bot scheduler disabled!")
            else:
                messagebox.showerror("Error", "Failed to remove bot cron jobs")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to uninstall bot scheduler: {str(e)}")
    

    # =================================================================
    # LinkedIn Applier Methods
    # =================================================================
    
    def get_linkedin_schedule_display(self):
        """Get formatted LinkedIn schedule times for display"""
        times = self.config.data.get("linkedin_schedule_times", [])
        if not times:
            return "None"
        return ", ".join(times)
    
    def is_linkedin_scheduler_installed(self):
        """Check if LinkedIn cron jobs are installed"""
        try:
            result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
            return 'linkedin_job_applier.py' in result.stdout
        except:
            return False
    
    def update_linkedin_stats_display(self):
        """Update LinkedIn statistics display"""
        self.linkedin_today_label.config(text=str(self.linkedin_stats.data.get("today_count", 0)))
        self.linkedin_week_label.config(text=str(self.linkedin_stats.get_week_total()))
        self.linkedin_total_label.config(text=str(self.linkedin_stats.data.get("total_applications", 0)))
    
    def reset_linkedin_stats(self):
        """Reset LinkedIn statistics"""
        if messagebox.askyesno("Reset LinkedIn Stats", "Are you sure you want to reset all LinkedIn statistics?"):
            self.linkedin_stats.data = {
                "total_applications": 0,
                "today_count": 0,
                "last_run": None,
                "success_count": 0,
                "daily_history": {}
            }
            self.linkedin_stats.save()
            self.update_linkedin_stats_display()
            messagebox.showinfo("Success", "LinkedIn statistics have been reset!")
    
    def start_linkedin_applier(self):
        """Start the LinkedIn job applier"""
        if self.is_linkedin_running:
            return
        
        # Check credentials
        if not self.config.data.get("linkedin_email") or not self.config.data.get("linkedin_password"):
            messagebox.showerror("Error", "Please configure LinkedIn credentials in Settings first!")
            return
        
        try:
            target = int(self.linkedin_target_var.get())
            if target <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid positive number for target applications.")
            return
        
        # Update UI
        self.is_linkedin_running = True
        self.linkedin_start_btn.config(state=tk.DISABLED)
        self.linkedin_stop_btn.config(state=tk.NORMAL)
        self.linkedin_status_var.set("Running")
        self.linkedin_status_label.config(foreground="blue")
        
        # Add log entry
        self.append_log(f"\n{'='*60}\n")
        self.append_log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting LinkedIn job applier...\n")
        self.append_log(f"Target: {target} applications\n")
        if hasattr(self, "linkedin_headless_var") and self.linkedin_headless_var.get():
            self.append_log("Mode: Background (headless)\n")
        else:
            self.append_log("Mode: Visible browser\n")
        self.append_log(f"{'='*60}\n\n")
        
        # Start process in thread
        headless_var = getattr(self, "linkedin_headless_var", None)
        headless = bool(headless_var.get()) if headless_var is not None else True
        self.config.data["ui_headless_linkedin"] = headless
        self.config.save()
        threading.Thread(target=self.run_linkedin_applier, args=(target, headless), daemon=True).start()
    
    def run_linkedin_applier(self, target: int, headless: bool):
        """Run the LinkedIn job applier process"""
        try:
            # Get job titles
            job_titles = self.config.data.get("job_titles", "").strip()
            
            # Build command
            cmd = [sys.executable, str(LINKEDIN_APPLIER_SCRIPT), "--target", str(target)]
            if headless:
                cmd.append("--headless")
            
            # Add job titles if provided
            if job_titles:
                titles_list = [title.strip() for title in job_titles.split(',')]
                cmd.extend(["--keywords"] + titles_list)
            
            # Run process
            self.linkedin_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(SCRIPT_DIR)
            )
            
            # Stream output
            for line in iter(self.linkedin_process.stdout.readline, ''):
                if not self.is_linkedin_running:
                    break
                self.log_from_thread(line)
            
            self.linkedin_process.wait()
            
            # Update stats
            self.linkedin_stats.data = self.linkedin_stats.load()
            self.ui_call(self.update_linkedin_stats_display)
            
            # Update UI
            self.ui_call(self.linkedin_status_var.set, "Completed")
            self.ui_call(self.linkedin_status_label.config, foreground="green")
            self.log_from_thread(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] LinkedIn applier finished.\n")
            
        except Exception as e:
            self.log_from_thread(f"Error: {str(e)}\n")
            self.ui_call(self.linkedin_status_var.set, "Error")
            self.ui_call(self.linkedin_status_label.config, foreground="red")
        finally:
            self.is_linkedin_running = False
            self.ui_call(self.linkedin_start_btn.config, state=tk.NORMAL)
            self.ui_call(self.linkedin_stop_btn.config, state=tk.DISABLED)
    
    def stop_linkedin_applier(self):
        """Stop the LinkedIn job applier"""
        if self.linkedin_process and self.linkedin_process.poll() is None:
            self.linkedin_process.terminate()
            self.append_log(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] LinkedIn applier stopped by user.\n")
        
        self.is_linkedin_running = False
        self.linkedin_status_var.set("Stopped")
        self.linkedin_status_label.config(foreground="orange")
        self.linkedin_start_btn.config(state=tk.NORMAL)
        self.linkedin_stop_btn.config(state=tk.DISABLED)
    
    def show_linkedin_scheduler_config(self):
        """Show LinkedIn scheduler configuration dialog"""
        sched_win = tk.Toplevel(self.root)
        sched_win.title("Configure LinkedIn Schedule")
        sched_win.geometry("440x380")
        sched_win.transient(self.root)
        sched_win.grab_set()
        sched_win.configure(bg=self.colors["bg"])
        
        # Center the window
        sched_win.update_idletasks()
        x = (sched_win.winfo_screenwidth() // 2) - (440 // 2)
        y = (sched_win.winfo_screenheight() // 2) - (380 // 2)
        sched_win.geometry(f"440x380+{x}+{y}")
        
        # Main frame
        main = ttk.Frame(sched_win, padding="20")
        main.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main, text="LinkedIn Scheduled Run Times", style="SectionHeader.TLabel").pack(pady=(0, 10))
        
        ttk.Label(main, text="The LinkedIn applier will run automatically at these times each day:",
                 wraplength=380, style="Muted.TLabel").pack(pady=(0, 10))
        
        # Listbox for times
        list_frame = ttk.Frame(main)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        times_list = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            height=8,
            background=self.colors["surface"],
            foreground=self.colors["text"],
            selectbackground=self.colors["accent"],
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            borderwidth=0
        )
        times_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=times_list.yview)
        
        # Populate current times
        current_times = self.config.data.get("linkedin_schedule_times", [])
        for time in current_times:
            times_list.insert(tk.END, time)
        
        # Add/Remove controls
        control_frame = ttk.Frame(main)
        control_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(control_frame, text="Add time (HH:MM):").pack(side=tk.LEFT)
        time_var = tk.StringVar(value="09:00")
        time_entry = ttk.Entry(control_frame, textvariable=time_var, width=10)
        time_entry.pack(side=tk.LEFT, padx=5)
        
        def add_time():
            time_str = time_var.get()
            try:
                hour, minute = map(int, time_str.split(':'))
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    formatted = f"{hour:02d}:{minute:02d}"
                    if formatted not in times_list.get(0, tk.END):
                        times_list.insert(tk.END, formatted)
                else:
                    raise ValueError
            except:
                messagebox.showerror("Invalid Time", "Please use HH:MM format (00:00 to 23:59)")
        
        ttk.Button(control_frame, text="Add", command=add_time).pack(side=tk.LEFT)
        
        def remove_time():
            selection = times_list.curselection()
            if selection:
                times_list.delete(selection[0])
        
        ttk.Button(control_frame, text="Remove Selected", command=remove_time).pack(side=tk.LEFT, padx=5)
        
        # Buttons
        button_frame = ttk.Frame(main)
        button_frame.pack(fill=tk.X)
        
        def save_schedule():
            times = list(times_list.get(0, tk.END))
            self.config.data["linkedin_schedule_times"] = times
            self.config.save()
            self.linkedin_schedule_text.set(self.get_linkedin_schedule_display())
            
            if self.linkedin_scheduler_enabled_var.get():
                self.install_linkedin_scheduler()
                messagebox.showinfo("Success", "LinkedIn schedule updated and applied to cron!")
            else:
                messagebox.showinfo("Success", "LinkedIn schedule saved! Enable the scheduler to apply changes.")
            
            sched_win.destroy()
        
        ttk.Button(button_frame, text="Save", command=save_schedule).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=sched_win.destroy).pack(side=tk.RIGHT)
    
    def toggle_linkedin_scheduler(self):
        """Enable or disable the LinkedIn scheduler"""
        if self.linkedin_scheduler_enabled_var.get():
            self.uninstall_linkedin_scheduler()
        else:
            self.install_linkedin_scheduler()
    
    def install_linkedin_scheduler(self):
        """Install cron jobs for LinkedIn scheduled times"""
        try:
            times = self.config.data.get("linkedin_schedule_times", [])
            if not times:
                messagebox.showwarning("No Schedule", "Please configure at least one scheduled time first.")
                return
            
            # Get current crontab
            try:
                result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
                current_cron = result.stdout
            except:
                current_cron = ""
            
            # Remove existing LinkedIn entries
            lines = [line for line in current_cron.split('\n') if 'linkedin_job_applier.py' not in line]
            
            # Add new entries
            for time_str in times:
                hour, minute = time_str.split(':')
                cron_line = f"{minute} {hour} * * * cd {SCRIPT_DIR} && {sys.executable} {LINKEDIN_APPLIER_SCRIPT} --target 30 --headless >> {LOG_FILE} 2>&1"
                lines.append(cron_line)
            
            # Write new crontab
            new_cron = '\n'.join(lines) + '\n'
            process = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE, text=True)
            process.communicate(input=new_cron)
            
            if process.returncode == 0:
                self.linkedin_scheduler_enabled_var.set(True)
                self.linkedin_scheduler_toggle_btn.config(text="Disable Scheduler")
                messagebox.showinfo("Success", f"LinkedIn scheduler enabled! Jobs will run at: {self.get_linkedin_schedule_display()}")
            else:
                messagebox.showerror("Error", "Failed to install LinkedIn cron jobs")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to install LinkedIn scheduler: {str(e)}")
    
    def uninstall_linkedin_scheduler(self):
        """Remove LinkedIn cron jobs"""
        try:
            result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
            current_cron = result.stdout
            
            # Remove LinkedIn entries
            lines = [line for line in current_cron.split('\n') if 'linkedin_job_applier.py' not in line]
            
            # Write new crontab
            new_cron = '\n'.join(lines) + '\n'
            process = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE, text=True)
            process.communicate(input=new_cron)
            
            if process.returncode == 0:
                self.linkedin_scheduler_enabled_var.set(False)
                self.linkedin_scheduler_toggle_btn.config(text="Enable Scheduler")
                messagebox.showinfo("Success", "LinkedIn scheduler disabled!")
            else:
                messagebox.showerror("Error", "Failed to remove LinkedIn cron jobs")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to uninstall LinkedIn scheduler: {str(e)}")
    
    def quit_app(self):
        """Quit the application"""
        if self.is_running:
            if not messagebox.askyesno("Quit", 
                                      "Job applier is running. Are you sure you want to quit?"):
                return
            self.stop_applier()
        
        self.stop_log_thread = True
        self._stop_ui_pump = True
        self.root.quit()


def main():
    """Main entry point"""
    # Check if applier script exists
    if not APPLIER_SCRIPT.exists():
        messagebox.showerror(
            "Script Not Found",
            f"Could not find naukri_job_applier.py in:\n{SCRIPT_DIR}\n\n"
            "Please ensure both files are in the same directory."
        )
        sys.exit(1)
    
    # Create and run GUI
    root = tk.Tk()
    
    # macOS: avoid the "topmost" trick (it can cause flaky click handling on some systems).
    try:
        root.after(0, root.lift)
        root.after(0, root.focus_force)
    except Exception:
        pass
    
    app = JobApplierGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
