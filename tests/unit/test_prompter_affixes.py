"""
Tests for attaching prefix/suffix concepts onto the concepts in a mix.

Affixes cannot join the mix as ordinary entries -- "-punk" on its own is not a
concept -- so _attach_affixes rewrites the mix in place. The sampled counts are
stubbed rather than read from the concept files so the assertions are about the
attaching rule and not about what happens to be in prefixes.txt.
"""

import pytest

from sd_runner.prompts.prompter import Prompter
from tests.utils import make_prompter


@pytest.fixture
def prompter():
    return make_prompter()


def stub_affixes(prompter, monkeypatch, prefixes=(), suffixes=()):
    monkeypatch.setattr(prompter.concepts, "get_prefixes",
                        lambda config, multiplier=1.0: list(prefixes))
    monkeypatch.setattr(prompter.concepts, "get_suffixes",
                        lambda config, multiplier=1.0: list(suffixes))


# ---------------------------------------------------------------------------
# Which entries can host an affix
# ---------------------------------------------------------------------------

class TestHostEligibility:
    @pytest.mark.parametrize("entry", ["cathedral", "moss", "Gothic"])
    def test_a_bare_word_is_eligible(self, entry):
        assert Prompter._can_take_affix(entry)

    @pytest.mark.parametrize("entry", [
        "ancient stone bridge",   # would read as modifying only the end word
        "rust-eaten",             # already hyphenated
        "(cathedral)",            # carries emphasis
        "[cathedral]",
        "$$random_word",          # not expanded yet
        "35mm",
        "",
    ])
    def test_anything_else_is_not(self, entry):
        assert not Prompter._can_take_affix(entry)


# ---------------------------------------------------------------------------
# Attaching
# ---------------------------------------------------------------------------

class TestAttachAffixes:
    def test_prefix_joins_the_front_of_a_host(self, prompter, monkeypatch):
        stub_affixes(prompter, monkeypatch, prefixes=["neo-"])
        mix = ["cathedral"]
        prompter._attach_affixes(mix)
        assert mix == ["neo-cathedral"]

    def test_suffix_joins_the_end_of_a_host(self, prompter, monkeypatch):
        stub_affixes(prompter, monkeypatch, suffixes=["-punk"])
        mix = ["cathedral"]
        prompter._attach_affixes(mix)
        assert mix == ["cathedral-punk"]

    def test_the_mix_does_not_grow(self, prompter, monkeypatch):
        """An affix modifies a concept; it never becomes one."""
        stub_affixes(prompter, monkeypatch, prefixes=["neo-"], suffixes=["-punk"])
        mix = ["cathedral", "moss", "rain"]
        prompter._attach_affixes(mix)
        assert len(mix) == 3

    def test_an_ineligible_entry_is_left_alone(self, prompter, monkeypatch):
        stub_affixes(prompter, monkeypatch, suffixes=["-punk"])
        mix = ["ancient stone bridge", "cathedral"]
        prompter._attach_affixes(mix)
        assert mix[0] == "ancient stone bridge"
        assert mix[1] == "cathedral-punk"

    def test_nothing_sampled_leaves_the_mix_untouched(self, prompter, monkeypatch):
        stub_affixes(prompter, monkeypatch)
        mix = ["cathedral", "moss"]
        prompter._attach_affixes(mix)
        assert mix == ["cathedral", "moss"]


class TestHostsAreNotShared:
    def test_each_affix_takes_its_own_host(self, prompter, monkeypatch):
        stub_affixes(prompter, monkeypatch, prefixes=["neo-", "cyber-", "ur-"])
        mix = ["cathedral", "moss", "rain"]
        prompter._attach_affixes(mix)
        # Which prefix lands on which host is random; that all three hosts were
        # used exactly once is not.
        assert sorted(entry.split("-")[0] + "-" for entry in mix) == \
            ["cyber-", "neo-", "ur-"]
        assert sorted(entry.split("-")[1] for entry in mix) == \
            ["cathedral", "moss", "rain"]

    def test_no_host_takes_both_a_prefix_and_a_suffix(self, prompter, monkeypatch):
        """Stacked affixes turn the concept into noise."""
        stub_affixes(prompter, monkeypatch, prefixes=["neo-"], suffixes=["-punk"])
        mix = ["cathedral", "moss"]
        prompter._attach_affixes(mix)
        for entry in mix:
            assert not (entry.startswith("neo-") and entry.endswith("-punk"))

    def test_no_host_takes_two_of_the_same_kind(self, prompter, monkeypatch):
        stub_affixes(prompter, monkeypatch, suffixes=["-punk", "-clad"])
        mix = ["cathedral", "moss"]
        prompter._attach_affixes(mix)
        assert sorted(mix) in ([  # order depends on which host each landed on
            sorted(["cathedral-punk", "moss-clad"]),
            sorted(["cathedral-clad", "moss-punk"]),
        ])


class TestCappedByAvailableHosts:
    def test_more_affixes_than_hosts_drops_the_excess(self, prompter, monkeypatch):
        stub_affixes(prompter, monkeypatch, prefixes=["neo-", "cyber-", "ur-"])
        mix = ["cathedral"]
        prompter._attach_affixes(mix)
        assert mix in (["neo-cathedral"], ["cyber-cathedral"], ["ur-cathedral"])

    def test_no_eligible_host_applies_nothing(self, prompter, monkeypatch):
        stub_affixes(prompter, monkeypatch, prefixes=["neo-"], suffixes=["-punk"])
        mix = ["ancient stone bridge", "(cathedral)"]
        prompter._attach_affixes(mix)
        assert mix == ["ancient stone bridge", "(cathedral)"]

    def test_an_empty_mix_is_handled(self, prompter, monkeypatch):
        stub_affixes(prompter, monkeypatch, prefixes=["neo-"])
        mix = []
        prompter._attach_affixes(mix)
        assert mix == []

    def test_the_smaller_list_is_not_starved(self, prompter, monkeypatch):
        """Trimming takes from the longer list, so one host means one each."""
        stub_affixes(prompter, monkeypatch,
                     prefixes=["neo-", "cyber-", "ur-"], suffixes=["-punk"])
        mix = ["cathedral", "moss"]
        prompter._attach_affixes(mix)
        assert sum(1 for entry in mix if entry.endswith("-punk")) == 1
        assert sum(1 for entry in mix
                   if entry.startswith(("neo-", "cyber-", "ur-"))) == 1
