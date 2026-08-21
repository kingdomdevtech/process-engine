import pytest

from process_engine.expressions import ExpressionError, resolve

SCOPE = {
    "trigger": {"total": 250, "customer": "ACME"},
    "variables": {"region": "EU"},
    "steps": {"fetch": {"output": {"total": 42, "items": [{"sku": "A-1"}, {"sku": "B-2"}]}}},
    "input": {"message": "hi"},
}


def test_whole_expression_keeps_type():
    assert resolve("{{ steps.fetch.output.total }}", SCOPE) == 42
    assert resolve("{{ trigger }}", SCOPE) == {"total": 250, "customer": "ACME"}


def test_interpolation_renders_text():
    assert resolve("Total: {{ steps.fetch.output.total }}!", SCOPE) == "Total: 42!"


def test_list_index():
    assert resolve("{{ steps.fetch.output.items.1.sku }}", SCOPE) == "B-2"


def test_recursive_containers():
    value = {"a": ["{{ variables.region }}"], "b": {"c": "{{ input.message }}"}}
    assert resolve(value, SCOPE) == {"a": ["EU"], "b": {"c": "hi"}}


def test_non_strings_untouched():
    assert resolve(7, SCOPE) == 7
    assert resolve(None, SCOPE) is None


def test_missing_path_raises():
    with pytest.raises(ExpressionError, match="nope"):
        resolve("{{ steps.fetch.output.nope }}", SCOPE)
