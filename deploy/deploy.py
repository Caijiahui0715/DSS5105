"""Put this project on the AWS server and (re)start it; deploy/README.md says how to set the server up.

    .venv\\Scripts\\python.exe deploy\\deploy.py          # upload the code and restart
    .venv\\Scripts\\python.exe deploy\\deploy.py --data   # also upload output-final-delivery and import it

The code uploaded is what Git would commit: tracked files and new ones .gitignore does not exclude,
without output-final-delivery, tmp and Claude outputs; it stops if a .env or another secret would go
along. deploy/server.env goes up as it is, to ~/dss5105-config on the server. Needs git, and ssh and
scp, which Windows 10 and 11 have built in.
"""

import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "deploy"
SETTINGS = HERE / "server.env"
DATA = ROOT / "output-final-delivery"
UPLOAD = "dss5105-upload"
# Not part of the code: the group's data goes up only with --data; the rest is local scratch.
LEFT_OUT = ("output-final-delivery/", "tmp/", "Claude outputs/")
SECRETS = {".env", "server.env", ".onemap_token.json"}
USER = "ubuntu"


def settings() -> dict[str, str]:
    if not SETTINGS.exists():
        sys.exit("Copy deploy/server.env.example to deploy/server.env first and fill it in as its comments say.")
    values = {}
    for line in SETTINGS.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.strip().startswith("#"):
            values[key.strip()] = value.strip()
    missing = [key for key in ("SITE_ADDRESS", "SSH_KEY") if not values.get(key)]
    if missing:
        sys.exit(f"deploy/server.env is missing {', '.join(missing)}. Fill it in and run again.")
    if not Path(values["SSH_KEY"]).is_file():
        sys.exit(f"The key file SSH_KEY points to was not found: {values['SSH_KEY']}")
    return values


def code_files() -> list[str]:
    try:
        listed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"git is needed to list the files to upload, but it could not run: {error}")
    names = sorted({name for name in listed.decode("utf-8").split("\0") if name})
    names = [name for name in names if not name.startswith(LEFT_OUT) and (ROOT / name).is_file()]
    secrets = [name for name in names if Path(name).name in SECRETS]
    if secrets:
        sys.exit(f"These files must not be uploaded; add them to .gitignore first: {', '.join(secrets)}")
    return names


def pack(path: Path, base: Path, names: list[str]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name in names:
            archive.add(base / name, arcname=name, recursive=False)


def current_ip() -> str:
    try:
        with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=5) as response:
            return f"your IP now is {response.read().decode().strip()}"
    except OSError:
        return "open https://checkip.amazonaws.com in a browser to see your IP now"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    flags = set(sys.argv[1:])
    if flags - {"--data"}:
        sys.exit(__doc__)
    with_data = "--data" in flags
    values = settings()
    site = values["SITE_ADDRESS"]
    target = f"{USER}@{site}"
    options = ["-i", values["SSH_KEY"], "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15"]

    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        # Copied next to the archives so scp gets plain file names, not paths starting with C:.
        shutil.copy(SETTINGS, folder / "server.env")
        shutil.copy(HERE / "remote.sh", folder / "remote.sh")
        uploads = ["code.tar.gz", "server.env", "remote.sh"]
        names = code_files()
        pack(folder / "code.tar.gz", ROOT, names)
        print(f"Code: {len(names)} files")
        if with_data:
            if not DATA.is_dir():
                sys.exit("There is no output-final-delivery folder, which --data uploads.")
            data = [f"output-final-delivery/{path.name}" for path in sorted(DATA.iterdir()) if path.is_file()]
            uploads.append("data.tar.gz")
            pack(folder / "data.tar.gz", ROOT, data)
            print(f"Listing data: {len(data)} files")

        if subprocess.run(["ssh", *options, target, f"mkdir -p -m 700 ~/{UPLOAD}"]).returncode:
            sys.exit(
                f"Cannot reach {site} over SSH (port 22). Most often your network has changed: in the EC2 security group, set the "
                f"SSH rule's source to your current IP ({current_ip()}). For other causes, see \"When something goes wrong\" in deploy/README.md."
            )
        if subprocess.run(["scp", *options, *uploads, f"{target}:{UPLOAD}/"], cwd=folder).returncode:
            sys.exit("The upload failed; see scp's error above.")
    # Run from a file, not piped in: docker compose would otherwise read the rest of the script.
    command = f"cd ~/{UPLOAD} && tr -d '\\r' < remote.sh > remote-lf.sh && bash remote-lf.sh{' --data' if with_data else ''}"
    if subprocess.run(["ssh", *options, target, command]).returncode:
        sys.exit("Something failed on the server; see the output above. Common cases are under \"When something goes wrong\" in deploy/README.md.")
    print(f"\nDone: https://{site} (the first time, the HTTPS certificate takes about half a minute to work)")


if __name__ == "__main__":
    main()
