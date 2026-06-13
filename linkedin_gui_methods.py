"""
LinkedIn GUI Methods for job_applier_gui.py
These methods should be added to the JobApplierGUI class in job_applier_gui.py

Instructions for Integration:
1. Insert setup_linkedin_tab method after setup_naukri_bot_tab (around line 441)
2. Add all helper methods before quit_app method (around line 1247)  
3. Update show_settings method to include LinkedIn credentials (see below)
"""

# =============================================================================
# METHOD 1: LinkedIn Tab Setup (insert after setup_naukri_bot_tab at ~line 441)
# =============================================================================

def setup_linkedin_tab(self, parent):
    """Setup LinkedIn Applier tab content"""
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(2, weight=1)
    
    # Control Panel
    control_frame = ttk.LabelFrame(parent, text="LinkedIn Job Application Controls", padding="10")
    control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
    control_frame.columnconfigure(4, weight=1)
    
    # Row 1: Target Applications
    ttk.Label(control_frame, text="Target Applications:").grid(row=0, column=0, sticky=tk.W)
    self.linkedin_target_var = tk.StringVar(value="30")
    ttk.Entry(control_frame, textvariable=self.linkedin_target_var, width=10).grid(row=0, column=1, padx=5, sticky=tk.W)
    
    self.linkedin_start_btn = ttk.Button(control_frame, text="▶ Start LinkedIn Applying",
                                       command=self.start_linkedin_applier, width=20)
    self.linkedin_start_btn.grid(row=0, column=2, padx=5)
    
    self.linkedin_stop_btn = ttk.Button(control_frame, text="⬛ Stop",
                                      command=self.stop_linkedin_applier, state=tk.DISABLED, width=12)
    self.linkedin_stop_btn.grid(row=0, column=3, padx=5)
    
    ttk.Label(control_frame, text="Status:").grid(row=0, column=4, padx=(20, 5), sticky=tk.E)
    self.linkedin_status_var = tk.StringVar(value="Idle")
    self.linkedin_status_label = ttk.Label(control_frame, textvariable=self.linkedin_status_var,
                                         font=('Arial', 10, 'bold'), foreground='gray')
    self.linkedin_status_label.grid(row=0, column=5, sticky=tk.W)
    
    # Row 2: Info about shared job titles
    ttk.Label(control_frame, text="Job Titles:", font=('Arial', 9), foreground='gray').grid(
        row=1, column=0, columnspan=6, sticky=tk.W, pady=(10, 0))
    ttk.Label(control_frame, text="Using shared job titles from settings", 
             font=('Arial', 9), foreground='blue').grid(row=2, column=0, columnspan=6, sticky=tk.W)
    
    # Statistics Panel
    stats_frame = ttk.LabelFrame(parent, text="LinkedIn Application Statistics", padding="10")
    stats_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
    
    # Stats labels
    ttk.Label(stats_frame, text="Today:").grid(row=0, column=0, sticky=tk.W)
    self.linkedin_today_label = ttk.Label(stats_frame, text="0", font=('Arial', 12, 'bold'))
    self.linkedin_today_label.grid(row=0, column=1, padx=10)
    
    ttk.Label(stats_frame, text="This Week:").grid(row=0, column=2, padx=(20, 0), sticky=tk.W)
    self.linkedin_week_label = ttk.Label(stats_frame, text="0", font=('Arial', 12, 'bold'))
    self.linkedin_week_label.grid(row=0, column=3, padx=10)
    
    ttk.Label(stats_frame, text="Total:").grid(row=0, column=4, padx=(20, 0), sticky=tk.W)
    self.linkedin_total_label = ttk.Label(stats_frame, text="0", font=('Arial', 12, 'bold'))
    self.linkedin_total_label.grid(row=0, column=5, padx=10)
    
    # Reset stats button
    ttk.Button(stats_frame, text="Reset Stats", command=self.reset_linkedin_stats).grid(
        row=0, column=6, padx=(20, 0))
    
    # Scheduler Panel
    scheduler_frame = ttk.LabelFrame(parent, text="Automated Schedule", padding="10")
    scheduler_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
    scheduler_frame.columnconfigure(1, weight=1)
    
    ttk.Label(scheduler_frame, text="Scheduled Times:").grid(row=0, column=0, sticky=tk.W)
    self.linkedin_schedule_text = tk.StringVar(value=self.get_linkedin_schedule_display())
    ttk.Label(scheduler_frame, textvariable=self.linkedin_schedule_text,
             font=('Arial', 10)).grid(row=0, column=1, sticky=tk.W, padx=10)
    
    ttk.Button(scheduler_frame, text="Configure Schedule",
              command=self.show_linkedin_scheduler_config).grid(row=0, column=2, padx=5)
    
    self.linkedin_scheduler_enabled_var = tk.BooleanVar(value=self.is_linkedin_scheduler_installed())
    self.linkedin_scheduler_toggle_btn = ttk.Button(scheduler_frame,
                                          text="Enable Scheduler" if not self.linkedin_scheduler_enabled_var.get() else "Disable Scheduler",
                                          command=self.toggle_linkedin_scheduler)
    self.linkedin_scheduler_toggle_btn.grid(row=0, column=3, padx=5)


# =============================================================================
# HELPER METHODS (insert before quit_app method at ~line 1247)
# =============================================================================

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
    self.append_log(f"{'='*60}\n\n")
    
    # Start process in thread
    threading.Thread(target=self.run_linkedin_applier, args=(target,), daemon=True).start()

def run_linkedin_applier(self, target: int):
    """Run the LinkedIn job applier process"""
    try:
        # Get job titles
        job_titles = self.config.data.get("job_titles", "").strip()
        
        # Build command
        cmd = [sys.executable, str(LINKEDIN_APPLIER_SCRIPT), "--target", str(target)]
        
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
            self.append_log(line)
        
        self.linkedin_process.wait()
        
        # Update stats
        self.linkedin_stats.data = self.linkedin_stats.load()
        self.root.after(0, self.update_linkedin_stats_display)
        
        # Update UI
        self.root.after(0, lambda: self.linkedin_status_var.set("Completed"))
        self.root.after(0, lambda: self.linkedin_status_label.config(foreground="green"))
        self.root.after(0, self.append_log, f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] LinkedIn applier finished.\n")
        
    except Exception as e:
        self.root.after(0, self.append_log, f"Error: {str(e)}\n")
        self.root.after(0, lambda: self.linkedin_status_var.set("Error"))
        self.root.after(0, lambda: self.linkedin_status_label.config(foreground="red"))
    finally:
        self.is_linkedin_running = False
        self.root.after(0, lambda: self.linkedin_start_btn.config(state=tk.NORMAL))
        self.root.after(0, lambda: self.linkedin_stop_btn.config(state=tk.DISABLED))

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
    # Similar to show_scheduler_config but for LinkedIn
    sched_win = tk.Toplevel(self.root)
    sched_win.title("Configure LinkedIn Schedule")
    sched_win.geometry("400x350")
    sched_win.transient(self.root)
    sched_win.grab_set()
    
    # Center the window
    sched_win.update_idletasks()
    x = (sched_win.winfo_screenwidth() // 2) - (400 // 2)
    y = (sched_win.winfo_screenheight() // 2) - (350 // 2)
    sched_win.geometry(f"400x350+{x}+{y}")
    
    # Main frame
    main = ttk.Frame(sched_win, padding="20")
    main.pack(fill=tk.BOTH, expand=True)
    
    ttk.Label(main, text="LinkedIn Scheduled Run Times", 
             font=('Arial', 12, 'bold')).pack(pady=(0, 10))
    
    ttk.Label(main, text="The LinkedIn applier will run automatically at these times each day:",
             wraplength=350).pack(pady=(0, 10))
    
    # Listbox for times
    list_frame = ttk.Frame(main)
    list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
    
    scrollbar = ttk.Scrollbar(list_frame)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    times_list = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, height=8)
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
            cron_line = f"{minute} {hour} * * * cd {SCRIPT_DIR} && {sys.executable} {LINKEDIN_APPLIER_SCRIPT} --target 30 >> {LOG_FILE} 2>&1"
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


# =============================================================================
# SETTINGS DIALOG UPDATES
# Add these fields to the show_settings method (around line 493-570)
# =============================================================================

"""
Add after the Naukri Password field (around line 524):

# === LINKEDIN CREDENTIALS ===
ttk.Label(main, text="LinkedIn Credentials", font=('Arial', 12, 'bold')).grid(
    row=5, column=0, sticky=tk.W, pady=(10, 10))

# LinkedIn Email
ttk.Label(main, text="LinkedIn Email:", font=('Arial', 10, 'bold')).grid(
    row=6, column=0, sticky=tk.W, pady=(0, 5))
linkedin_email_var = tk.StringVar(value=self.config.data.get("linkedin_email", ""))
linkedin_email_entry = ttk.Entry(main, textvariable=linkedin_email_var, width=40)
linkedin_email_entry.grid(row=7, column=0, sticky=(tk.W, tk.E), pady=(0, 15))

# LinkedIn Password
ttk.Label(main, text="LinkedIn Password:", font=('Arial', 10, 'bold')).grid(
    row=8, column=0, sticky=tk.W, pady=(0, 5))
linkedin_password_var = tk.StringVar(value=self.config.data.get("linkedin_password", ""))
linkedin_password_entry = ttk.Entry(main, textvariable=linkedin_password_var, width=40, show="•")
linkedin_password_entry.grid(row=9, column=0, sticky=(tk.W, tk.E), pady=(0, 15))

# LinkedIn Phone
ttk.Label(main, text="LinkedIn Phone (for applications):", font=('Arial', 10, 'bold')).grid(
    row=10, column=0, sticky=tk.W, pady=(0, 5))
linkedin_phone_var = tk.StringVar(value=self.config.data.get("linkedin_phone", ""))
linkedin_phone_entry = ttk.Entry(main, textvariable=linkedin_phone_var, width=40)
linkedin_phone_entry.grid(row=11, column=0, sticky=(tk.W, tk.E), pady=(0, 15))

Then in the save_settings function, add:
    self.config.data["linkedin_email"] = linkedin_email_var.get()
    self.config.data["linkedin_password"] = linkedin_password_var.get()
    self.config.data["linkedin_phone"] = linkedin_phone_var.get()

And update the window geometry to: settings_win.geometry("650x700")
"""
