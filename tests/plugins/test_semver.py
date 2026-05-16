import pytest

from claude_workspaces.plugins import semver


def test_parse_strict_version():
    v = semver.parse_version("1.2.3")
    assert (v.major, v.minor, v.patch) == (1, 2, 3)
    assert str(v) == "1.2.3"


@pytest.mark.parametrize(
    "bad",
    ["1.2", "1", "v1.2.3", "1.2.3-rc1", "1.2.3+build", "", "abc"],
)
def test_parse_rejects_non_strict(bad):
    with pytest.raises(ValueError):
        semver.parse_version(bad)


def test_satisfies_range():
    assert semver.satisfies("1.0.0", ">=1.0.0 <2.0.0")
    assert semver.satisfies("1.5.2", ">=1.0.0 <2.0.0")
    assert not semver.satisfies("2.0.0", ">=1.0.0 <2.0.0")
    assert not semver.satisfies("0.9.9", ">=1.0.0 <2.0.0")


def test_satisfies_exact():
    assert semver.satisfies("1.2.3", "1.2.3")
    assert semver.satisfies("1.2.3", "==1.2.3")
    assert not semver.satisfies("1.2.4", "1.2.3")
