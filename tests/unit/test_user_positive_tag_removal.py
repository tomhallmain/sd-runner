"""Removal notices for tags the user typed into the positive prompt.

The default notice says that tags were removed and does not name them. Naming
the blacklist item that matched is a separate option and stays off.
"""

from sd_runner.globals import BlacklistMode, BlacklistPromptMode, PromptMode
from sd_runner.prompts.blacklist import Blacklist, BlacklistItem


def test_a_blocked_tag_is_removed_and_the_rest_is_kept():
    Blacklist.add_item(BlacklistItem("forbidden"))
    cleaned, removed = Blacklist.strip_user_positive_tags(
        "a calm lake, forbidden, golden hour"
    )
    assert cleaned == "a calm lake, golden hour"
    assert "forbidden" in removed


def test_the_default_notice_does_not_name_the_tag_or_the_item():
    Blacklist.add_item(BlacklistItem("forbidden"))
    _cleaned, removed = Blacklist.strip_user_positive_tags("forbidden pose, soft light")
    notice = Blacklist.user_tag_removal_notice(removed)
    assert notice == "One or more tags were removed due to blacklist failure."
    assert "forbidden" not in notice


def test_naming_the_matched_item_adds_the_blacklist_item_only():
    Blacklist.add_item(BlacklistItem("forbidden"))
    _cleaned, removed = Blacklist.strip_user_positive_tags("a forbidden pose, soft light")
    Blacklist.set_blacklist_name_matched_item(True)
    notice = Blacklist.user_tag_removal_notice(removed)
    assert notice.startswith("One or more tags were removed due to blacklist failure.")
    assert "Matched blacklist items: forbidden" in notice
    assert "a forbidden pose" not in notice


def test_fail_prompt_does_not_strip_the_text():
    Blacklist.set_blacklist_mode(BlacklistMode.FAIL_PROMPT)
    Blacklist.add_item(BlacklistItem("forbidden"))
    text = "a calm lake, forbidden"
    assert Blacklist.strip_user_positive_tags(text) == (text, {})


def test_an_nsfw_exemption_leaves_the_prompt_alone():
    Blacklist.blacklist_prompt_mode = BlacklistPromptMode.ALLOW_IN_NSFW
    Blacklist.add_item(BlacklistItem("forbidden"))
    text = "forbidden, soft light"
    assert Blacklist.strip_user_positive_tags(text, PromptMode.NSFW) == (text, {})


def test_a_clean_prompt_is_unchanged():
    Blacklist.add_item(BlacklistItem("forbidden"))
    text = "a calm lake, golden hour"
    assert Blacklist.strip_user_positive_tags(text) == (text, {})
