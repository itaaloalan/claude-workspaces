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


# ---------- ordenação e __str__ de Version ----------

def test_version_ordering():
    assert semver.parse_version("1.0.0") < semver.parse_version("1.0.1")
    assert semver.parse_version("1.2.0") < semver.parse_version("1.10.0")
    assert semver.parse_version("2.0.0") > semver.parse_version("1.9.9")


def test_version_equality():
    assert semver.parse_version("1.2.3") == semver.parse_version("1.2.3")


def test_parse_version_strips_whitespace():
    assert str(semver.parse_version("  1.2.3  ")) == "1.2.3"


def test_parse_version_non_string_raises():
    with pytest.raises(ValueError):
        semver.parse_version(123)  # type: ignore[arg-type]


# ---------- operadores de constraint ----------

def test_satisfies_greater_than():
    assert semver.satisfies("2.0.0", ">1.0.0")
    assert not semver.satisfies("1.0.0", ">1.0.0")


def test_satisfies_less_or_equal():
    assert semver.satisfies("1.0.0", "<=1.0.0")
    assert not semver.satisfies("1.0.1", "<=1.0.0")


def test_satisfies_greater_or_equal_boundary():
    assert semver.satisfies("1.0.0", ">=1.0.0")


def test_satisfies_multiple_constraints_all_must_hold():
    assert semver.satisfies("1.5.0", ">=1.0.0 <=2.0.0 >1.4.9")
    assert not semver.satisfies("1.5.0", ">=1.0.0 <1.5.0")


# ---------- parse_range erros ----------

@pytest.mark.parametrize("bad", ["", "   ", ">>1.0.0", "1.2", "~1.0.0", "^2.0.0"])
def test_parse_range_invalid(bad):
    with pytest.raises(ValueError):
        semver.parse_range(bad)


def test_parse_range_equals_normalized_to_double():
    cons = semver.parse_range("=1.2.3")
    assert cons[0].op == "=="
