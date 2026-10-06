"""scripts/deploy.py and scripts/release.py: the version arithmetic, and that
the tool explains itself without touching anything."""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"_scripts_{name}", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"_scripts_{name}"] = module  # a dataclass looks its module up
    spec.loader.exec_module(module)
    return module


deploy = load("deploy")
release = load("release")


def test_one_bump_each_way():
    assert deploy.bumped((0, 14, 0), "minor") == "v0.15.0"
    assert deploy.bumped((0, 14, 2), "patch") == "v0.14.3"
    assert deploy.bumped((0, 14, 2), "major") == "v1.0.0"


def test_the_deploy_tool_and_the_release_script_agree():
    for current in [(0, 14, 0), (1, 2, 3)]:
        assert release.nxt(current) == deploy.bumped(current, "minor")
        assert release.nxt(current, patch=True) == deploy.bumped(current, "patch")
        assert release.nxt(current, major=True) == deploy.bumped(current, "major")


def test_only_release_tags_are_versions():
    assert deploy.parse("v0.14.0") == (0, 14, 0)
    assert deploy.parse("v0.14") is None
    assert deploy.parse("0.14.0") is None


def test_explain_says_how_it_fits_without_touching_anything():
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "deploy.py"), "explain"], capture_output=True, text=True, check=True
    ).stdout
    assert "ONE version number" in out and "follow the main branch" in out


def test_an_unknown_step_is_refused_plainly():
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "deploy.py"), "prod"], capture_output=True, text=True)
    assert done.returncode == 1 and "unknown: prod" in done.stderr
