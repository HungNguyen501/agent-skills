"""Fixtures for the skill script tests"""
import pytest

from tests.mocks import make_skill
from tests.skills.helpers import VARIANTS, load_variant


@pytest.fixture(name="env", params=sorted(VARIANTS))
def gen_env(request, tmp_path, monkeypatch):
    """(module, hub, dest, skills_dir, run) for one scaffolder variant, with a hub holding skills alpha and beta"""
    variant = request.param
    module = load_variant(variant)
    hub = tmp_path / "hub"
    domain = hub / "skills" / "demo"
    make_skill(domain, "alpha", files={"references/a.md": "alpha\n"})
    make_skill(domain, "beta")
    dest = tmp_path / "dest"
    dest.mkdir()
    monkeypatch.setattr(module, "hub_revision", lambda _hub: "rev1")

    def run(*extra):
        return module.main(["--hub", str(hub), "--dest", str(dest), *extra])

    return module, hub, dest, dest / VARIANTS[variant][0], run
