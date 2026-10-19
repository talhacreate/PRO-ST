"""
PRO ST Paid Tour Manager — Launcher & Auto-Setup Script (bot.py)
Project Folder: C:\Users\cm\Documents\MY BOT
Main Bot File : pro_st_paid_tour_manager.py

Usage:
    python bot.py
"""

import os
import sys
import subprocess

TARGET_FILE = "pro_st_paid_tour_manager.py"
ENV_FILE = ".env"
TOKEN_FILE = "token.txt"


def print_banner():
    print("=" * 65)
    print("      PRO ST PAID TOUR MANAGER — LAUNCHER (bot.py)")
    print("=" * 65)


def check_python_version():
    if sys.version_info < (3, 8):
        print(f"[ERROR] Python 3.8+ is required. You are using Python {sys.version}")
        sys.exit(1)


def check_dependencies():
    try:
        import discord
        print(f"[OK] discord.py version {discord.__version__} is installed.")
    except ImportError:
        print("\n[!] 'discord.py' is not installed in this environment.")
        print("    Installing 'discord.py' now, please wait...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "discord.py"], check=True)
            print("[OK] Successfully installed discord.py!\n")
        except Exception as e:
            print(f"[ERROR] Failed to install discord.py: {e}")
            print("Please run manually: pip install discord.py")
            sys.exit(1)


def get_token():
    # 1. Check OS Environment variable
    token = os.getenv("DISCORD_BOT_TOKEN")
    if token and token.strip():
        return token.strip()

    # 2. Check .env file
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DISCORD_BOT_TOKEN="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
        except Exception:
            pass

    # 3. Check token.txt file
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                val = f.read().strip()
                if val:
                    return val
        except Exception:
            pass

    # 4. Prompt user in console
    print("\n" + "-" * 65)
    print(" [!] DISCORD_BOT_TOKEN is not configured yet.")
    print(" Please enter your Discord Bot Token below.")
    print(" (It will be safely saved to .env so you do not need to retype it)")
    print("-" * 65)
    try:
        user_input = input("Enter Bot Token: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        sys.exit(0)

    if user_input:
        # Save to .env for future automatic runs
        try:
            with open(ENV_FILE, "w", encoding="utf-8") as f:
                f.write(f"DISCORD_BOT_TOKEN={user_input}\n")
            print(f"[OK] Saved token to {ENV_FILE}")
        except Exception as e:
            print(f"[Note] Could not save to {ENV_FILE}: {e}")
        return user_input
    else:
        print("[ERROR] Token cannot be empty. Please provide a valid bot token.")
        sys.exit(1)


def main():
    print_banner()
    check_python_version()

    # Verify main bot script presence
    if not os.path.exists(TARGET_FILE):
        print(f"\n[ERROR] '{TARGET_FILE}' was not found in:")
        print(f"        {os.getcwd()}")
        print(f"\nPlease make sure '{TARGET_FILE}' is placed in the exact same")
        print("folder as this 'bot.py' script.")
        input("\nPress Enter to exit...")
        sys.exit(1)

    print(f"[OK] Located main bot script: {TARGET_FILE}")

    # Check dependencies
    check_dependencies()

    # Resolve token
    token = get_token()
    os.environ["DISCORD_BOT_TOKEN"] = token

    # Check probot.db
    if os.path.exists("probot.db"):
        print("[OK] Existing 'probot.db' found. Tournaments and data preserved.")
    else:
        print("[Note] 'probot.db' will be automatically created on startup.")

    print("\n" + "=" * 65)
    print("  STARTING PRO ST PAID TOUR MANAGER...")
    print("  Press Ctrl + C in this window at any time to stop the bot.")
    print("=" * 65 + "\n")

    try:
        subprocess.run([sys.executable, TARGET_FILE], check=True)
    except KeyboardInterrupt:
        print("\n[OK] Bot stopped by user (Ctrl+C). Goodbye!")
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Bot process exited with code {e.returncode}")
    except Exception as e:
        print(f"\n[ERROR] Unexpected error while running bot: {e}")


if __name__ == "__main__":
    main()