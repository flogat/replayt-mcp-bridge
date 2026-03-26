"""Runnable example workflows for replayt."""

from replayt_examples import catalog as _catalog

ExampleSpec = _catalog.ExampleSpec
PACKAGED_EXAMPLES = _catalog.PACKAGED_EXAMPLES
get_packaged_example = _catalog.get_packaged_example
list_packaged_examples = _catalog.list_packaged_examples

__all__ = [
    "ExampleSpec",
    "PACKAGED_EXAMPLES",
    "get_packaged_example",
    "list_packaged_examples",
]
