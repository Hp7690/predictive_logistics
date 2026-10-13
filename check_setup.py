"""Run: python check_setup.py  -> checks that Step 1 tools are installed."""
import shutil, subprocess, sys

tools = {"python": ["python", "--version"], "node": ["node", "--version"],
         "git": ["git", "--version"], "docker": ["docker", "--version"], "code": ["code", "--version"]}
ok = True
for name, cmd in tools.items():
    exe = shutil.which(cmd[0]) or (shutil.which("python3") if name == "python" else None)
    if not exe:
        print(f"[MISSING] {name}"); ok = False; continue
    out = subprocess.run([exe] + cmd[1:], capture_output=True, text=True).stdout.strip().splitlines()
    print(f"[OK] {name}: {out[0] if out else 'installed'}")
if sys.version_info < (3, 11):
    print("[WARN] Python 3.11+ recommended"); ok = False
print("\nAll set." if ok else "\nInstall the missing tools, then run again.")
