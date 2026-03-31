import json
import os
import subprocess
import sys
from pathlib import Path


CONFIG_PATH = Path("config.json")
STATE_DIR = Path("/var/lib/minictl")
BASE_ROOTFS = Path("rootfs/alpine")


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def prepare_container_dirs(container_id: str) -> dict:
    container_dir = STATE_DIR / container_id
    upper = container_dir / "upper"
    work = container_dir / "work"
    merged = container_dir / "merged"

    for p in (container_dir, upper, work, merged):
        p.mkdir(parents=True, exist_ok=True)

    return {
        "container_dir": container_dir,
        "upper": upper,
        "work": work,
        "merged": merged,
    }

def mount_overlay(lower: Path, upper: Path, work: Path, merged: Path) -> None:
    options = f"lowerdir={lower},upperdir={upper},workdir={work}"
    subprocess.run(
        [
            "mount",
            "-t",
            "overlay",
            "overlay",
            "-o",
            options,
            str(merged),
        ],
        check=True,
    )

def umount_overlay(merged: Path) -> None:
    subprocess.run(["umount", str(merged)], check=True)

def run_container_init(merged: Path, hostname: str, cwd: str, args: list[str]) -> int:
    subprocess.run(["hostname", hostname], check=True)

    os.chroot(merged)
    os.chdir("/")

    os.makedirs("/proc", exist_ok=True)
    subprocess.run(["mount", "-t", "proc", "proc", "/proc"], check=True)

    os.chdir(cwd)

    print(f"HOSTNAME={os.uname().nodename}")
    print(f"PID={os.getpid()}")
    sys.stdout.flush()

    os.execvp(args[0], args)

def run_in_container(merged: Path, hostname: str, cwd: str, args: list[str]) -> int:
    cmd = [
        "unshare",
        "--fork",
        "--pid",
        "--mount",
        "--uts",
        sys.executable,
        str(Path(__file__).resolve()),
        "__init__",
        str(merged),
        hostname,
        cwd,
        *args,
    ]
    result = subprocess.run(cmd)
    return result.returncode

def main() -> None:
    if len(sys.argv) >= 6 and sys.argv[1] == "__init__":
        merged = Path(sys.argv[2])
        hostname = sys.argv[3]
        cwd = sys.argv[4]
        args = sys.argv[5:]
        rc = run_container_init(merged, hostname, cwd, args)
        sys.exit(rc)

    if len(sys.argv) < 2:
        print(f"Usage: sudo {sys.argv[0]} <container-id>")
        sys.exit(1)

    container_id = sys.argv[1]

    cfg = load_config(CONFIG_PATH)
    hostname = cfg.get("hostname", "container")
    process = cfg.get("process", {})
    args = process.get("args", ["/bin/sh"])
    cwd = process.get("cwd", "/")

    dirs = prepare_container_dirs(container_id)

    print(f"container id: {container_id}")
    print(f"hostname: {hostname}")
    print(f"cwd: {cwd}")
    print(f"args: {args}")
    print(f"lowerdir: {BASE_ROOTFS}")
    print(f"upperdir: {dirs['upper']}")
    print(f"workdir: {dirs['work']}")
    print(f"merged: {dirs['merged']}")

    try:
        mount_overlay(
            lower=BASE_ROOTFS,
            upper=dirs["upper"],
            work=dirs["work"],
            merged=dirs["merged"],
        )
        print("overlay mounted")

        rc = run_in_container(
            merged=dirs["merged"],
            hostname=hostname,
            cwd=cwd,
            args=args,
        )

        print(f"container exit code: {rc}")
        sys.exit(rc)

    finally:
        try:
            umount_overlay(dirs["merged"])
            print("overlay unmounted")
        except Exception:
            pass

if __name__ == "__main__":
    main()