"""Frequent prompt tag list state (non-UI)."""


class FrequentTags:
    tags = []

    @staticmethod
    def set_recent_tags(tags):
        FrequentTags.tags = list(tags)
