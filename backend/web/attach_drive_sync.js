window.driveSyncApi = {
  tokenClient: null,
  clientId: null,

  updateBadge: function(status) {
    const badge = document.getElementById("driveSyncBadge");
    if (!badge) return;
    badge.classList.remove("animate-spin");
    if (status === 'disconnected') {
      badge.style.stroke = "#ef4444"; // red-500
    } else if (status === 'connected') {
      badge.style.stroke = "#94a3b8"; // slate-400
    } else if (status === 'syncing') {
      badge.style.stroke = "#f59e0b"; // amber-500
      badge.classList.add("animate-spin");
    } else if (status === 'success') {
      badge.style.stroke = "#10b981"; // emerald-500
      setTimeout(() => this.updateBadge('connected'), 3000);
    } else if (status === 'error') {
      badge.style.stroke = "#ef4444"; // red-500
      setTimeout(() => this.updateBadge('connected'), 3000);
    }
  },

  connect: function() {
    if (this.tokenClient) {
      this.tokenClient.requestAccessToken();
    } else {
      alert("Google OAuth is not initialized yet. If you just loaded the page, please wait a second. Otherwise, check if GOOGLE_CLIENT_ID is set correctly.");
    }
  },

  disconnect: function() {
    sessionStorage.removeItem("googleToken");
    document.getElementById("driveSyncNotConnected").style.display = "flex";
    document.getElementById("driveSyncConnected").style.display = "none";
    this.updateBadge('disconnected');
  },

  backup: async function() {
    const token = sessionStorage.getItem("googleToken");
    if (!token) return;
    this.updateBadge('syncing');
    try {
      const res = await fetch("/api/config", {
        credentials: "include"
      });
      if (!res.ok) throw new Error(`Failed to read config (HTTP ${res.status})`);
      const config = await res.json();
      await window.googleDrive.uploadBackup(token, config);
      this.updateBadge('success');
    } catch(e) {
      this.updateBadge('error');
      alert("Backup error: " + e.message);
    }
  },

  restore: async function() {
    const token = sessionStorage.getItem("googleToken");
    if (!token) return;
    this.updateBadge('syncing');
    try {
      const backup = await window.googleDrive.downloadBackup(token);
      if (!backup) {
        this.updateBadge('error');
        throw new Error("No valid backup found in Google Drive");
      }
      if (confirm("Restore this backup? This will replace your current settings.")) {
        const res = await fetch("/api/config", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify(backup)
        });
        if (!res.ok) {
          this.updateBadge('error');
          throw new Error("Failed to save restored config");
        }
        this.updateBadge('success');
        if (typeof window.refreshAll === "function") {
          await window.refreshAll();
        } else {
          window.location.reload();
        }
      } else {
        this.updateBadge('connected');
      }
    } catch(e) {
      this.updateBadge('error');
      alert("Restore error: " + e.message);
    }
  },

  init: async function() {
    let sysInfo = {};
    try {
      const res = await fetch("/api/system_info", { credentials: "include" });
      sysInfo = await res.json();
    } catch(e) {}
    
    this.clientId = sysInfo.google_client_id;
    
    // Check if token exists
    const stored = sessionStorage.getItem("googleToken");
    if (stored && window.googleDrive) {
      const valid = await window.googleDrive.validateGoogleToken(stored);
      if (valid) {
        document.getElementById("driveSyncNotConnected").style.display = "none";
        document.getElementById("driveSyncConnected").style.display = "block";
        this.updateBadge('connected');
      } else {
        this.updateBadge('disconnected');
      }
    } else {
      this.updateBadge('disconnected');
    }
    
    const tryInitTokenClient = () => {
      if (this.clientId && window.google && window.google.accounts && window.google.accounts.oauth2) {
        this.tokenClient = google.accounts.oauth2.initTokenClient({
          client_id: this.clientId,
          scope: 'https://www.googleapis.com/auth/drive.appdata',
          callback: (tokenResponse) => {
            if (tokenResponse && tokenResponse.access_token) {
              sessionStorage.setItem("googleToken", tokenResponse.access_token);
              document.getElementById("driveSyncNotConnected").style.display = "none";
              document.getElementById("driveSyncConnected").style.display = "block";
              this.updateBadge('success');
            }
          },
        });
      } else if (this.clientId) {
        setTimeout(tryInitTokenClient, 1000);
      }
    };
    tryInitTokenClient();

    // Close popup if clicking outside
    document.addEventListener("click", (e) => {
       const container = document.getElementById("driveSyncMenuContainer");
       if (container && !container.contains(e.target)) {
          const popup = document.getElementById("driveSyncPopup");
          if(popup) popup.style.display = "none";
       }
    });

    window.addEventListener("google-token-expired", () => {
       document.getElementById("driveSyncNotConnected").style.display = "flex";
       document.getElementById("driveSyncConnected").style.display = "none";
       this.updateBadge('disconnected');
    });
  }
};

// Initialize as soon as possible
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => window.driveSyncApi.init());
} else {
  window.driveSyncApi.init();
}
