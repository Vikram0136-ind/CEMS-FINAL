#!/usr/bin/env python3
"""
CEMS Desktop Launcher
Opens the Campus Event Management System in your default browser automatically
"""

import os
import sys
import time
import webbrowser
import subprocess
from pathlib import Path

def launch_cems():
    """Launch Flask app and open in browser"""
    
    print("=" * 60)
    print("  🎪 CEMS - Campus Event Management System")
    print("  Amritsar Group of Colleges")
    print("=" * 60)
    print()
    
    # Get project root
    project_root = Path(__file__).parent
    
    # Activate virtual environment and run Flask
    print("⏳ Starting CEMS server...")
    
    # Change to project directory
    os.chdir(project_root)
    
    # Start Flask in background
    if sys.platform == "win32":
        # Windows
        flask_process = subprocess.Popen(
            [sys.executable, "app.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
    else:
        # macOS/Linux
        flask_process = subprocess.Popen(
            [sys.executable, "app.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
    
    print("✅ Server started!")
    print()
    
    # Wait for server to start
    time.sleep(3)
    
    # Open browser
    print("🌐 Opening browser...")
    print()
    print("Welcome! Your CEMS portal is loading...")
    print()
    print("📍 Server: http://127.0.0.1:5001")
    print()
    print("🔐 Development accounts are seeded only when no users exist.")
    print("   Use the passwords printed by the setup script or reset them after first launch.")
    print()
    print("📞 AGC Contact: +91 88720 09950 (24/7 Support)")
    print()
    print("-" * 60)
    
    # Open in default browser
    webbrowser.open("http://127.0.0.1:5001", new=1, autoraise=True)
    
    print("✅ Browser opened!")
    print("Keep this window open while using CEMS.")
    print("Close this window to stop the server.")
    print("-" * 60)
    
    # Keep process running
    try:
        flask_process.wait()
    except KeyboardInterrupt:
        print("\n🛑 Stopping CEMS server...")
        flask_process.terminate()
        flask_process.wait()
        print("✅ Server stopped. Goodbye!")

if __name__ == "__main__":
    launch_cems()
