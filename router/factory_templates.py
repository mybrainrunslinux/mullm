"""Create a committed starter contract from resources shipped in the wheel."""
from pathlib import Path
import shutil
import subprocess


def initialize(name: str, destination: Path) -> Path:
    if name != "csv-json":
        raise ValueError("Unknown factory starter")
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("Choose a new directory; existing projects are never overwritten")
    if not shutil.which("git"):
        raise ValueError("Install Git before creating a factory project")
    source = Path(__file__).with_name("templates") / name
    shutil.copytree(source, destination)
    subprocess.run(["git", "init", str(destination)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(destination), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(destination), "-c", "user.name=muLLM Factory",
                    "-c", "user.email=factory@localhost", "commit", "-m", "Approve starter acceptance contract"],
                   check=True, capture_output=True)
    return destination
