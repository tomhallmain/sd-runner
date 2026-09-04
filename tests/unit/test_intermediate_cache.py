"""Reusing a pre-pass generation instead of repeating it.

The cache's whole value is that it hits, so most of these are about the key
being neither too narrow (never reuses) nor too wide (returns the wrong image),
and about a hit being trustworthy: the files live in a directory this app does
not manage, so a stored path is a claim to verify, not a fact.
"""

from sd_runner.runs.intermediate_cache import IntermediateCache


def _prompt(**kwargs):
    base = {
        "positive_tags": "black and white",
        "negative_tags": "",
        "use_negative": False,
        "workflow_type": "IMAGE_EDIT",
        "max_variants": 1,
    }
    base.update(kwargs)
    return base


def _image(tmp_path, name="source.png", content=b"pixels"):
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


# ---------------------------------------------------------------------------
# What the key distinguishes
# ---------------------------------------------------------------------------

class TestTheKey:
    def test_the_same_pass_over_the_same_image_matches(self, app_cache, tmp_path):
        source = _image(tmp_path)
        assert IntermediateCache.key_for(_prompt(), source) == \
            IntermediateCache.key_for(_prompt(), source)

    def test_a_different_image_does_not(self, app_cache, tmp_path):
        a = _image(tmp_path, "a.png")
        b = _image(tmp_path, "b.png")
        assert IntermediateCache.key_for(_prompt(), a) != IntermediateCache.key_for(_prompt(), b)

    def test_different_prompt_text_does_not(self, app_cache, tmp_path):
        source = _image(tmp_path)
        assert IntermediateCache.key_for(_prompt(), source) != \
            IntermediateCache.key_for(_prompt(positive_tags="a drawing"), source)

    def test_a_different_workflow_does_not(self, app_cache, tmp_path):
        source = _image(tmp_path)
        assert IntermediateCache.key_for(_prompt(), source) != \
            IntermediateCache.key_for(_prompt(workflow_type="CONTROLNET"), source)

    def test_editing_the_source_file_does_not(self, app_cache, tmp_path):
        """Same path, different contents -- the old intermediate is not of it."""
        source = _image(tmp_path)
        before = IntermediateCache.key_for(_prompt(), source)
        import os
        with open(source, "wb") as f:
            f.write(b"different pixels entirely")
        os.utime(source, (0, 0))
        assert IntermediateCache.key_for(_prompt(), source) != before

    def test_an_unused_negative_does_not_split_the_key(self, app_cache, tmp_path):
        """It is not sent, so two prompts differing only there are one pass."""
        source = _image(tmp_path)
        assert IntermediateCache.key_for(_prompt(negative_tags="colour"), source) == \
            IntermediateCache.key_for(_prompt(negative_tags="something else"), source)

    def test_a_used_negative_does(self, app_cache, tmp_path):
        source = _image(tmp_path)
        assert IntermediateCache.key_for(_prompt(negative_tags="colour", use_negative=True), source) != \
            IntermediateCache.key_for(_prompt(negative_tags="grain", use_negative=True), source)

    def test_only_the_named_parts_matter(self, app_cache, tmp_path):
        """Seed, model and the sampler settings are deliberately out. On the
        default seed of -1, which draws fresh per generation, a seed-keyed
        entry would never be reused and 'run it once' would never happen."""
        source = _image(tmp_path)
        assert IntermediateCache.key_for(_prompt(), source) == \
            IntermediateCache.key_for(
                _prompt(seed=12345, model="other.safetensors", steps=40), source
            )


# ---------------------------------------------------------------------------
# Storing and reusing
# ---------------------------------------------------------------------------

class TestStoreAndReuse:
    def test_a_stored_intermediate_comes_back(self, app_cache, tmp_path):
        made = _image(tmp_path, "intermediate.png")
        IntermediateCache.put("k", made)
        assert IntermediateCache.get("k") == made

    def test_an_unknown_key_misses(self, app_cache):
        assert IntermediateCache.get("never-stored") is None

    def test_a_vanished_file_misses(self, app_cache, tmp_path):
        """The output directory is not ours; a tidied folder must regenerate."""
        made = _image(tmp_path, "intermediate.png")
        IntermediateCache.put("k", made)
        import os
        os.remove(made)
        assert IntermediateCache.get("k") is None

    def test_a_vanished_file_is_dropped_rather_than_rechecked(self, app_cache, tmp_path):
        made = _image(tmp_path, "intermediate.png")
        IntermediateCache.put("k", made)
        import os
        os.remove(made)
        IntermediateCache.get("k")
        assert IntermediateCache.count("k") == 0

    def test_one_variant_replaces_rather_than_accumulates(self, app_cache, tmp_path):
        first = _image(tmp_path, "one.png")
        second = _image(tmp_path, "two.png")
        IntermediateCache.put("k", first, max_variants=1)
        IntermediateCache.put("k", second, max_variants=1)
        assert IntermediateCache.count("k") == 1

    def test_several_variants_accumulate_to_the_cap(self, app_cache, tmp_path):
        for i in range(5):
            IntermediateCache.put("k", _image(tmp_path, f"{i}.png"), max_variants=3)
        assert IntermediateCache.count("k") == 3

    def test_several_variants_are_rotated_between(self, app_cache, tmp_path):
        """Otherwise a variant count above one generates images nothing uses."""
        stored = {_image(tmp_path, f"{i}.png") for i in range(3)}
        for path in stored:
            IntermediateCache.put("k", path, max_variants=3)

        seen = {IntermediateCache.get("k") for _ in range(60)}
        assert seen == stored

    def test_storing_the_same_path_twice_does_not_double_count(self, app_cache, tmp_path):
        made = _image(tmp_path, "intermediate.png")
        IntermediateCache.put("k", made, max_variants=3)
        IntermediateCache.put("k", made, max_variants=3)
        assert IntermediateCache.count("k") == 1


# ---------------------------------------------------------------------------
# In-flight coordination
# ---------------------------------------------------------------------------

class TestLocking:
    def test_one_lock_per_key(self, app_cache):
        assert IntermediateCache.lock("a") is IntermediateCache.lock("a")

    def test_different_keys_do_not_block_each_other(self, app_cache):
        assert IntermediateCache.lock("a") is not IntermediateCache.lock("b")
