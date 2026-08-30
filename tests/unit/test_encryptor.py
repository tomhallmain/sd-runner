"""Unit tests for the consolidated key store in utils/encryptor.py.

macOS prompts per keychain item on first access, so the acceptance criterion
is the number of distinct keyring reads -- these count them directly against a
fake keyring rather than asserting on behaviour that only looks right.
"""

import json
import os
import sys

import pytest

import utils.encryptor as enc
from utils.utils import Utils


SERVICE = "TestService"
APP = "test_app"


class FakeKeyring:
    """Stands in for the keyring module, recording every access."""

    def __init__(self):
        self.store: dict = {}
        self.gets: list = []
        self.sets: list = []
        self.deletes: list = []

    def get_password(self, service, key):
        self.gets.append((service, key))
        return self.store.get((service, key))

    def set_password(self, service, key, value):
        self.sets.append((service, key))
        self.store[(service, key)] = value

    def delete_password(self, service, key):
        self.deletes.append((service, key))
        self.store.pop((service, key), None)

    def distinct_reads(self):
        """Every key read, including misses."""
        return {k for _s, k in self.gets}

    def existing_reads(self):
        """Keys read that actually held a value.

        The prompt-relevant measure: a read that misses has no keychain item to
        authorise access to, so it cannot prompt. A fresh install probes
        `{app}__salt` once looking for a pre-consolidation layout, and that
        miss should not count against the budget.
        """
        return {
            key for _service, key in self.gets
            if self.store.get((_service, key)) is not None
        }


@pytest.fixture
def fake_keyring(monkeypatch, tmp_path):
    fk = FakeKeyring()
    monkeypatch.setattr(enc, "keyring", fk)
    monkeypatch.setenv("SD_RUNNER_CACHE_DIR", str(tmp_path))
    # Pin the auto-backup destination inside tmp_path. Without this it would
    # detect the real machine's external drive and write key backups to it
    # during the test run. Tests that care set their own value over this one.
    monkeypatch.setenv(enc.KEY_BACKUP_DIR_ENV_VAR, str(tmp_path / "auto_backup"))
    enc._auto_backup_warned.clear()
    enc.clear_key_store_cache()
    yield fk
    enc.clear_key_store_cache()
    enc._auto_backup_warned.clear()


def _encryptor():
    """The standard (ECC) encryptor -- available without the oqs library."""
    return enc.PersonalStandardEncryptor


class TestKeyStorePath:
    def test_honours_the_cache_dir_override(self, fake_keyring, tmp_path):
        assert enc.key_store_path(SERVICE, APP).startswith(str(tmp_path))

    def test_namespaced_by_service_and_app(self, fake_keyring):
        one = enc.key_store_path(SERVICE, "app_one")
        two = enc.key_store_path(SERVICE, "app_two")
        other = enc.key_store_path("OtherService", "app_one")
        assert one != two != other and one != other

    def test_missing_store_reads_as_none(self, fake_keyring):
        assert enc.read_key_store(SERVICE, APP) is None

    def test_malformed_store_reads_as_none(self, fake_keyring):
        path = enc.key_store_path(SERVICE, APP)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("not json at all")
        assert enc.read_key_store(SERVICE, APP) is None

    def test_write_then_read_round_trips(self, fake_keyring):
        data = {"version": 1, enc.ENCRYPTOR_TYPE_KEY: "standard", "salt": "aa"}
        enc.write_key_store(SERVICE, APP, data)
        enc.clear_key_store_cache()
        assert enc.read_key_store(SERVICE, APP) == data


class TestKeychainAccessCount:
    """The ticket's actual requirement: at most two prompts."""

    def test_steady_state_run_touches_one_keychain_item(self, fake_keyring, tmp_path):
        """What a user sees on every run after the first."""
        _encryptor().generate_and_store_keys(SERVICE, APP)
        enc.clear_key_store_cache()          # new process
        fake_keyring.gets.clear()

        target = str(tmp_path / "payload.enc")
        enc.encrypt_data_to_file(b"hello", SERVICE, APP, target)
        enc.decrypt_data_from_file(target, SERVICE, APP)

        assert fake_keyring.distinct_reads() == {f"{APP}__passphrase"}

    def test_only_existing_item_read_on_a_fresh_install_is_the_passphrase(
        self, fake_keyring
    ):
        """First run probes for a legacy layout. That read misses, and a miss
        cannot prompt -- there is no item to authorise access to."""
        _encryptor().generate_and_store_keys(SERVICE, APP)
        assert fake_keyring.existing_reads() == {f"{APP}__passphrase"}

    def test_repeat_operations_do_not_re_read_the_keychain(
        self, fake_keyring, tmp_path
    ):
        """load_private_key runs per encrypt and decrypt, and store() is on a
        timer -- without caching this grows for the whole session."""
        target = str(tmp_path / "payload.enc")
        enc.encrypt_data_to_file(b"hello", SERVICE, APP, target)
        reads_after_first = len(fake_keyring.gets)
        for _ in range(5):
            enc.decrypt_data_from_file(target, SERVICE, APP)
        assert len(fake_keyring.gets) == reads_after_first

    def test_only_one_item_is_ever_written_to_the_keychain(self, fake_keyring, tmp_path):
        target = str(tmp_path / "payload.enc")
        enc.encrypt_data_to_file(b"hello", SERVICE, APP, target)
        enc.store_encrypted_password(SERVICE, APP, "base", "hunter2")
        assert {key for _s, key in fake_keyring.sets} == {f"{APP}__passphrase"}

    def test_no_chunked_items_are_written(self, fake_keyring):
        _encryptor().generate_and_store_keys(SERVICE, APP)
        assert not [k for _s, k in fake_keyring.sets if k.endswith("__count")]


class TestRoundTrip:
    def test_data_survives_encrypt_decrypt(self, fake_keyring, tmp_path):
        target = str(tmp_path / "payload.enc")
        enc.encrypt_data_to_file(b"some cache contents", SERVICE, APP, target)
        assert enc.decrypt_data_from_file(target, SERVICE, APP) == b"some cache contents"

    def test_password_round_trips_through_the_store(self, fake_keyring):
        _encryptor().generate_and_store_keys(SERVICE, APP)
        assert enc.store_encrypted_password(SERVICE, APP, "base", "hunter2")
        assert enc.retrieve_encrypted_password(SERVICE, APP, "base") == "hunter2"

    def test_password_lives_in_the_store_not_the_keychain(self, fake_keyring):
        _encryptor().generate_and_store_keys(SERVICE, APP)
        enc.store_encrypted_password(SERVICE, APP, "base", "hunter2")
        store = enc.read_key_store(SERVICE, APP)
        assert "base" in store[enc.PasswordManager.STORE_SECTION]
        # Nothing about the password reached the keychain.
        assert {key for _s, key in fake_keyring.sets} == {f"{APP}__passphrase"}
        assert fake_keyring.existing_reads() == {f"{APP}__passphrase"}

    def test_deleted_password_is_gone(self, fake_keyring):
        _encryptor().generate_and_store_keys(SERVICE, APP)
        enc.store_encrypted_password(SERVICE, APP, "base", "hunter2")
        enc.PasswordManager.delete_password(SERVICE, APP, "base")
        assert enc.retrieve_encrypted_password(SERVICE, APP, "base") is None


class TestMigrationFromLegacyLayout:
    """Reading the old per-item layout once, then retiring it."""

    def _seed_legacy(self, fake_keyring, cls=None):
        """Build a real legacy layout by writing chunked keychain items."""
        cls = cls or _encryptor()
        # Generate through the new path, then re-express it as legacy items.
        cls.generate_and_store_keys(SERVICE, APP)
        store = enc.read_key_store(SERVICE, APP)
        enc.delete_key_store(SERVICE, APP)

        def chunk(key, hex_value):
            base = enc.get_key_base(APP, key)
            parts = [hex_value[i:i + 500] for i in range(0, len(hex_value), 500)]
            fake_keyring.set_password(SERVICE, enc.namespaced_key(base, "count"), str(len(parts)))
            for i, part in enumerate(parts):
                fake_keyring.set_password(SERVICE, enc.namespaced_key(base, i), part)

        for key in (cls.SALT_KEY, cls.NONCE_KEY, cls.TAG_KEY):
            fake_keyring.set_password(SERVICE, enc.namespaced_key(APP, key), store[key])
        fake_keyring.set_password(
            SERVICE, enc.namespaced_key(APP, enc.ENCRYPTOR_TYPE_KEY),
            store[enc.ENCRYPTOR_TYPE_KEY],
        )
        chunk(cls.ENCRYPTED_PRIV_KEY, store[cls.ENCRYPTED_PRIV_KEY])
        chunk(cls.PUBLIC_KEY, store[cls.PUBLIC_KEY])
        enc.clear_key_store_cache()
        return store

    def test_legacy_layout_is_migrated_into_the_store(self, fake_keyring):
        original = self._seed_legacy(fake_keyring)
        migrated = _encryptor()._ensure_key_store(SERVICE, APP)
        assert migrated[_encryptor().PUBLIC_KEY] == original[_encryptor().PUBLIC_KEY]
        assert migrated[_encryptor().ENCRYPTED_PRIV_KEY] == (
            original[_encryptor().ENCRYPTED_PRIV_KEY]
        )

    def test_legacy_items_are_deleted_after_migration(self, fake_keyring):
        self._seed_legacy(fake_keyring)
        _encryptor()._ensure_key_store(SERVICE, APP)
        remaining = [k for _s, k in fake_keyring.store if k != f"{APP}__passphrase"]
        assert remaining == []

    def test_migration_is_not_repeated(self, fake_keyring):
        self._seed_legacy(fake_keyring)
        _encryptor()._ensure_key_store(SERVICE, APP)
        before = len(fake_keyring.gets)
        _encryptor()._ensure_key_store(SERVICE, APP)
        assert len(fake_keyring.gets) == before

    def test_legacy_items_survive_a_failed_store_write(self, fake_keyring, monkeypatch):
        """The old items are the only copy of the private key: never delete
        them unless the new store has been read back intact."""
        self._seed_legacy(fake_keyring)

        def _boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(enc, "write_key_store", _boom)
        _encryptor()._ensure_key_store(SERVICE, APP)

        assert fake_keyring.store.get((SERVICE, f"{APP}__salt"))
        assert fake_keyring.deletes == []

    def test_incomplete_legacy_layout_raises_and_is_left_alone(self, fake_keyring):
        """Salt present but nothing else. Returning None here would let
        generate_and_store_keys() mint new keys over a recoverable install."""
        fake_keyring.set_password(SERVICE, enc.namespaced_key(APP, "salt"), "aabb")
        with pytest.raises(enc.KeyMaterialError):
            _encryptor()._ensure_key_store(SERVICE, APP)
        assert fake_keyring.deletes == []

    def test_data_encrypted_before_migration_still_decrypts(
        self, fake_keyring, tmp_path
    ):
        target = str(tmp_path / "payload.enc")
        enc.encrypt_data_to_file(b"pre-migration", SERVICE, APP, target)
        self._seed_legacy_from_existing(fake_keyring, tmp_path)
        assert enc.decrypt_data_from_file(target, SERVICE, APP) == b"pre-migration"

    def _seed_legacy_from_existing(self, fake_keyring, tmp_path):
        """Convert the already-generated store back to the legacy layout."""
        cls = _encryptor()
        store = enc.read_key_store(SERVICE, APP)
        enc.delete_key_store(SERVICE, APP)
        for key in (cls.SALT_KEY, cls.NONCE_KEY, cls.TAG_KEY):
            fake_keyring.set_password(SERVICE, enc.namespaced_key(APP, key), store[key])
        fake_keyring.set_password(
            SERVICE, enc.namespaced_key(APP, enc.ENCRYPTOR_TYPE_KEY),
            store[enc.ENCRYPTOR_TYPE_KEY],
        )
        for key in (cls.ENCRYPTED_PRIV_KEY, cls.PUBLIC_KEY):
            base = enc.get_key_base(APP, key)
            value = store[key]
            parts = [value[i:i + 500] for i in range(0, len(value), 500)]
            fake_keyring.set_password(
                SERVICE, enc.namespaced_key(base, "count"), str(len(parts))
            )
            for i, part in enumerate(parts):
                fake_keyring.set_password(SERVICE, enc.namespaced_key(base, i), part)
        enc.clear_key_store_cache()


class TestPurge:
    def test_purge_removes_the_store(self, fake_keyring):
        _encryptor().generate_and_store_keys(SERVICE, APP)
        _encryptor().purge_keys(SERVICE, APP)
        assert enc.read_key_store(SERVICE, APP) is None


class TestRegenerationGuard:
    """New keys over a recoverable install would orphan everything already
    encrypted, with no way back -- so it must never happen silently."""

    def test_fresh_install_still_generates(self, fake_keyring):
        """The guard must not false-positive on a genuinely new install."""
        assert _encryptor().generate_and_store_keys(SERVICE, APP)

    def test_lost_key_store_raises_instead_of_regenerating(self, fake_keyring):
        _encryptor().generate_and_store_keys(SERVICE, APP)
        original = enc.read_key_store(SERVICE, APP)
        enc.delete_key_store(SERVICE, APP)   # store lost; passphrase remains

        with pytest.raises(enc.KeyMaterialError) as excinfo:
            _encryptor().generate_and_store_keys(SERVICE, APP)
        # Points at import, not export: with the store gone there is nothing
        # left to export from -- the way out is restoring an earlier backup.
        assert "import_key_material" in str(excinfo.value)
        assert "force_new" in str(excinfo.value)
        # And the old public key was not overwritten by a new one.
        assert enc.read_key_store(SERVICE, APP) is None
        assert original is not None

    def test_incomplete_legacy_layout_raises_and_keeps_entries(self, fake_keyring):
        fake_keyring.set_password(SERVICE, enc.namespaced_key(APP, "salt"), "aabb")
        with pytest.raises(enc.KeyMaterialError) as excinfo:
            _encryptor().generate_and_store_keys(SERVICE, APP)
        assert "incomplete" in str(excinfo.value)
        assert fake_keyring.store.get((SERVICE, f"{APP}__salt")) == "aabb"
        assert fake_keyring.deletes == []

    def test_force_new_deliberately_bypasses_the_guard(self, fake_keyring):
        _encryptor().generate_and_store_keys(SERVICE, APP)
        enc.delete_key_store(SERVICE, APP)
        # Explicitly asking to discard the old keys is allowed.
        assert _encryptor().generate_and_store_keys(SERVICE, APP, force_new=True)
        assert enc.read_key_store(SERVICE, APP) is not None

    def test_has_prior_key_material_detects_each_signal(self, fake_keyring):
        assert not enc.has_prior_key_material(SERVICE, APP)
        _encryptor().generate_and_store_keys(SERVICE, APP)
        assert enc.has_prior_key_material(SERVICE, APP)
        enc.delete_key_store(SERVICE, APP)
        # Passphrase alone is enough -- it survives migration and store loss.
        assert enc.has_prior_key_material(SERVICE, APP)

    def test_peek_passphrase_does_not_create_one(self, fake_keyring):
        assert enc.peek_passphrase(SERVICE, APP) is None
        assert fake_keyring.sets == []


class TestExportImportRecovery:
    def test_export_captures_store_and_passphrase(self, fake_keyring):
        _encryptor().generate_and_store_keys(SERVICE, APP)
        material = enc.export_key_material(SERVICE, APP)
        assert material["key_store"] == enc.read_key_store(SERVICE, APP)
        assert material["passphrase"]

    def test_export_writes_a_file_when_asked(self, fake_keyring, tmp_path):
        _encryptor().generate_and_store_keys(SERVICE, APP)
        out = str(tmp_path / "backup.json")
        enc.export_key_material(SERVICE, APP, output_path=out)
        with open(out, encoding="utf-8") as handle:
            assert json.load(handle)["passphrase"]

    def test_export_falls_back_to_legacy_items(self, fake_keyring):
        """The state a half-finished migration leaves behind."""
        _encryptor().generate_and_store_keys(SERVICE, APP)
        store = enc.read_key_store(SERVICE, APP)
        enc.delete_key_store(SERVICE, APP)
        for key in ("salt", "nonce", "tag", enc.ENCRYPTOR_TYPE_KEY):
            fake_keyring.set_password(SERVICE, enc.namespaced_key(APP, key), store[key])

        material = enc.export_key_material(SERVICE, APP)
        assert material["key_store"] is None
        assert material["legacy_items"]["salt"] == store["salt"]

    def test_export_import_restores_a_lost_store(self, fake_keyring, tmp_path):
        """The recovery the guard's message points at."""
        target = str(tmp_path / "payload.enc")
        enc.encrypt_data_to_file(b"irreplaceable", SERVICE, APP, target)
        material = enc.export_key_material(SERVICE, APP)

        enc.delete_key_store(SERVICE, APP)
        enc.clear_key_store_cache()
        with pytest.raises(enc.KeyMaterialError):
            enc.decrypt_data_from_file(target, SERVICE, APP)

        enc.import_key_material(material)
        assert enc.decrypt_data_from_file(target, SERVICE, APP) == b"irreplaceable"

    def test_import_rejects_empty_material(self, fake_keyring):
        with pytest.raises(enc.KeyMaterialError):
            enc.import_key_material(
                {"service_name": SERVICE, "app_identifier": APP,
                 "key_store": None, "legacy_items": None}
            )

    def test_default_location_is_a_service_folder_in_the_user_data_dir(
        self, monkeypatch
    ):
        """The data directory, not the cache one: XDG defines the cache as
        regenerable data, which a private key is not."""
        monkeypatch.delenv("SD_RUNNER_CACHE_DIR", raising=False)
        path = enc.key_store_path(SERVICE, APP)
        assert os.path.dirname(path) == os.path.join(Utils.user_data_dir(), SERVICE)

    def test_user_data_dir_is_not_the_cache_dir(self):
        assert ".cache" not in Utils.user_data_dir()



    def test_apps_sharing_a_service_share_one_folder(self, monkeypatch):
        """The point of keying the folder on the service: sd_runner, muse and
        weidr keep their key material together, one file each."""
        monkeypatch.delenv("SD_RUNNER_CACHE_DIR", raising=False)
        dirs = {
            os.path.dirname(enc.key_store_path(SERVICE, app))
            for app in ("weidr", "sd_runner", "muse")
        }
        files = {
            os.path.basename(enc.key_store_path(SERVICE, app))
            for app in ("weidr", "sd_runner", "muse")
        }
        assert len(dirs) == 1
        assert len(files) == 3

    def test_a_different_service_gets_a_different_folder(self, monkeypatch):
        monkeypatch.delenv("SD_RUNNER_CACHE_DIR", raising=False)
        assert os.path.dirname(enc.key_store_path(SERVICE, APP)) != os.path.dirname(
            enc.key_store_path("OtherService", APP)
        )

    def test_no_same_drive_copies_are_left_behind(self, fake_keyring):
        """Copies beside the original do not survive the failure that loses an
        irreplaceable key -- the drive. Off-drive export is the backup."""
        _encryptor().generate_and_store_keys(SERVICE, APP)
        enc.write_key_store(SERVICE, APP, enc.read_key_store(SERVICE, APP))
        directory = os.path.dirname(enc.key_store_path(SERVICE, APP))
        assert not [f for f in os.listdir(directory) if ".bak" in f or f.endswith(".tmp")]

    def test_interrupted_write_leaves_the_previous_store_intact(
        self, fake_keyring, tmp_path, monkeypatch
    ):
        """os.replace() is what makes a same-drive backup unnecessary."""
        target = str(tmp_path / "payload.enc")
        enc.encrypt_data_to_file(b"survives", SERVICE, APP, target)

        real_replace = os.replace

        def _fail_replace(src, dst):
            raise OSError("interrupted")

        monkeypatch.setattr(os, "replace", _fail_replace)
        with pytest.raises(OSError):
            enc.write_key_store(SERVICE, APP, {"encryptor_type": "standard", "junk": 1})
        monkeypatch.setattr(os, "replace", real_replace)

        enc.clear_key_store_cache()
        assert enc.decrypt_data_from_file(target, SERVICE, APP) == b"survives"

    def test_failed_migration_prints_recoverable_material(
        self, fake_keyring, monkeypatch, capsys
    ):
        """The reason it prints: the failure it runs on is a failure to write
        a file, so a file is no use as the escape hatch."""
        self._seed_legacy_for_migration(fake_keyring)

        def _boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(enc, "write_key_store", _boom)
        _encryptor()._ensure_key_store(SERVICE, APP)

        printed = capsys.readouterr().out
        assert "KEY MATERIAL RECOVERY DUMP" in printed
        # Enough to reconstruct: the dump parses and carries the private key.
        start = printed.index("{", printed.index("RECOVERY DUMP"))
        dumped = json.loads(printed[start:printed.rindex("}") + 1])
        assert dumped["key_store"]["encrypted_priv"]
        assert dumped["passphrase"]

    def _seed_legacy_for_migration(self, fake_keyring):
        cls = _encryptor()
        cls.generate_and_store_keys(SERVICE, APP)
        store = enc.read_key_store(SERVICE, APP)
        enc.delete_key_store(SERVICE, APP)
        for key in (cls.SALT_KEY, cls.NONCE_KEY, cls.TAG_KEY):
            fake_keyring.set_password(SERVICE, enc.namespaced_key(APP, key), store[key])
        fake_keyring.set_password(
            SERVICE, enc.namespaced_key(APP, enc.ENCRYPTOR_TYPE_KEY),
            store[enc.ENCRYPTOR_TYPE_KEY])
        for key in (cls.ENCRYPTED_PRIV_KEY, cls.PUBLIC_KEY):
            base = enc.get_key_base(APP, key)
            parts = [store[key][i:i + 500] for i in range(0, len(store[key]), 500)]
            fake_keyring.set_password(
                SERVICE, enc.namespaced_key(base, "count"), str(len(parts)))
            for i, part in enumerate(parts):
                fake_keyring.set_password(SERVICE, enc.namespaced_key(base, i), part)
        enc.clear_key_store_cache()
        return store

    def test_migration_names_a_real_drive_when_one_is_available(
        self, fake_keyring, tmp_path, monkeypatch, capsys
    ):
        """Migration is the moment the store becomes the only copy, so the
        backup must exist by the time it reports success -- and the location
        must be reported, so an unwanted copy is visible.

        Both branches are pinned explicitly rather than left to depend on
        whether the machine running the tests happens to have a drive mounted.
        """
        external = tmp_path / "mounted_drive"
        external.mkdir()
        monkeypatch.delenv(enc.KEY_BACKUP_DIR_ENV_VAR, raising=False)
        monkeypatch.setattr(
            Utils, "available_external_drives", staticmethod(lambda: [str(external)])
        )
        self._seed_legacy_for_migration(fake_keyring)
        _encryptor()._ensure_key_store(SERVICE, APP)

        backup = enc.default_key_backup_path(SERVICE, APP)
        assert os.path.exists(backup)
        with open(backup, encoding="utf-8") as handle:
            assert json.load(handle)["key_store"]["encrypted_priv"]

        printed = capsys.readouterr().out
        assert "Off-drive backup written to" in printed
        assert str(external / SERVICE) in printed

    def test_migration_warns_when_no_drive_is_available(
        self, fake_keyring, monkeypatch, capsys
    ):
        """Nothing is written locally as a consolation prize; the user is told
        the store is the only copy and how to give it somewhere to go."""
        monkeypatch.delenv(enc.KEY_BACKUP_DIR_ENV_VAR, raising=False)
        monkeypatch.setattr(Utils, "available_external_drives", staticmethod(lambda: []))
        self._seed_legacy_for_migration(fake_keyring)
        _encryptor()._ensure_key_store(SERVICE, APP)

        printed = capsys.readouterr().out
        assert enc.KEY_BACKUP_DIR_ENV_VAR in printed
        assert "only copy" in printed
        assert enc.default_key_backup_path(SERVICE, APP) is None

    def test_key_generation_backs_up_automatically(
        self, fake_keyring, tmp_path, monkeypatch
    ):
        """A backup nobody remembers to take protects nothing."""
        external = tmp_path / "external_drive"
        external.mkdir()
        monkeypatch.setenv(enc.KEY_BACKUP_DIR_ENV_VAR, str(external))

        _encryptor().generate_and_store_keys(SERVICE, APP)

        backup = enc.default_key_backup_path(SERVICE, APP)
        assert os.path.exists(backup)
        with open(backup, encoding="utf-8") as handle:
            assert json.load(handle)["key_store"]["encrypted_priv"]

    def test_backup_keeps_up_with_later_writes(
        self, fake_keyring, tmp_path, monkeypatch
    ):
        """A password stored after migration lives in the store too, so a
        one-shot backup would be missing it exactly when it mattered."""
        external = tmp_path / "external_drive"
        external.mkdir()
        monkeypatch.setenv(enc.KEY_BACKUP_DIR_ENV_VAR, str(external))
        _encryptor().generate_and_store_keys(SERVICE, APP)
        enc.store_encrypted_password(SERVICE, APP, "base", "hunter2")

        with open(enc.default_key_backup_path(SERVICE, APP), encoding="utf-8") as handle:
            backed_up = json.load(handle)
        assert "base" in backed_up["key_store"][enc.PasswordManager.STORE_SECTION]

    def test_backup_failure_does_not_fail_the_write(
        self, fake_keyring, monkeypatch, capsys
    ):
        monkeypatch.setattr(
            enc, "export_key_material",
            lambda *a, **k: (_ for _ in ()).throw(OSError("drive removed")),
        )
        monkeypatch.setattr(enc, "default_key_backup_path", lambda s, a: "/nope/x.json")

        _encryptor().generate_and_store_keys(SERVICE, APP)

        assert enc.read_key_store(SERVICE, APP) is not None  # store still written
        assert "backup failed" in capsys.readouterr().out

    def test_missing_drive_is_reported_once_not_per_write(
        self, fake_keyring, monkeypatch, capsys
    ):
        monkeypatch.delenv(enc.KEY_BACKUP_DIR_ENV_VAR, raising=False)
        monkeypatch.setattr(Utils, "available_external_drives", staticmethod(lambda: []))
        enc._auto_backup_warned.clear()

        _encryptor().generate_and_store_keys(SERVICE, APP)
        enc.store_encrypted_password(SERVICE, APP, "base", "hunter2")

        printed = capsys.readouterr().out
        assert printed.count(enc.KEY_BACKUP_DIR_ENV_VAR) == 1

    def test_auto_backup_can_be_switched_off(self, fake_keyring, tmp_path, monkeypatch):
        external = tmp_path / "external_drive"
        external.mkdir()
        monkeypatch.setenv(enc.KEY_BACKUP_DIR_ENV_VAR, str(external))
        monkeypatch.setattr(enc, "AUTO_BACKUP_KEY_STORE", False)

        _encryptor().generate_and_store_keys(SERVICE, APP)
        assert not os.path.exists(enc.default_key_backup_path(SERVICE, APP))

    def test_backup_adds_no_keychain_reads(self, fake_keyring, tmp_path, monkeypatch):
        """peek_passphrase must use the cache: an uncached read here would put
        a macOS prompt behind every key store write."""
        external = tmp_path / "external_drive"
        external.mkdir()
        monkeypatch.setenv(enc.KEY_BACKUP_DIR_ENV_VAR, str(external))
        _encryptor().generate_and_store_keys(SERVICE, APP)
        fake_keyring.gets.clear()

        enc.store_encrypted_password(SERVICE, APP, "base", "hunter2")
        assert fake_keyring.gets == []

    def test_env_var_sets_the_backup_destination(self, fake_keyring, tmp_path, monkeypatch):
        external = tmp_path / "external_drive"
        external.mkdir()
        monkeypatch.setenv(enc.KEY_BACKUP_DIR_ENV_VAR, str(external))
        path = enc.default_key_backup_path(SERVICE, APP)
        assert path.startswith(str(external))
        assert APP in os.path.basename(path)

    def test_backup_uses_the_same_service_folder_shape(self, tmp_path, monkeypatch):
        """One backup drive holds every app in the family, together."""
        external = tmp_path / "external_drive"
        external.mkdir()
        monkeypatch.setenv(enc.KEY_BACKUP_DIR_ENV_VAR, str(external))
        paths = [
            enc.default_key_backup_path(SERVICE, app)
            for app in ("weidr", "sd_runner")
        ]
        assert {os.path.dirname(p) for p in paths} == {str(external / SERVICE)}
        assert len({os.path.basename(p) for p in paths}) == 2

    def test_backup_writes_to_the_default_destination(
        self, fake_keyring, tmp_path, monkeypatch
    ):
        external = tmp_path / "external_drive"
        external.mkdir()
        monkeypatch.setenv(enc.KEY_BACKUP_DIR_ENV_VAR, str(external))
        _encryptor().generate_and_store_keys(SERVICE, APP)

        written = enc.backup_key_material(SERVICE, APP)
        assert written and os.path.exists(written)
        with open(written, encoding="utf-8") as handle:
            assert json.load(handle)["key_store"]

    def test_no_external_drive_reports_rather_than_writing_locally(
        self, fake_keyring, monkeypatch, capsys
    ):
        """A 'backup' on the system drive does not survive the failure it is
        for, so none is written and the caller is told."""
        monkeypatch.delenv(enc.KEY_BACKUP_DIR_ENV_VAR, raising=False)
        monkeypatch.setattr(Utils, "available_external_drives", staticmethod(lambda: []))
        _encryptor().generate_and_store_keys(SERVICE, APP)

        assert enc.backup_key_material(SERVICE, APP) is None
        assert enc.KEY_BACKUP_DIR_ENV_VAR in capsys.readouterr().out

    def test_detected_drive_is_used_when_no_env_var_is_set(
        self, fake_keyring, tmp_path, monkeypatch
    ):
        external = tmp_path / "mounted_drive"
        external.mkdir()
        monkeypatch.delenv(enc.KEY_BACKUP_DIR_ENV_VAR, raising=False)
        monkeypatch.setattr(
            Utils, "available_external_drives", staticmethod(lambda: [str(external)])
        )
        assert enc.default_key_backup_path(SERVICE, APP).startswith(str(external))

    def test_available_drives_excludes_unwritable_mounts(self, monkeypatch, tmp_path):
        readable = tmp_path / "mount"
        readable.mkdir()
        monkeypatch.setattr(os, "access", lambda p, mode: False)
        assert Utils.available_external_drives() == []

    def test_export_to_an_external_path_is_self_contained(
        self, fake_keyring, tmp_path
    ):
        """The actual backup policy: one file the user puts on another drive,
        holding everything needed to restore without the keychain."""
        target = str(tmp_path / "payload.enc")
        enc.encrypt_data_to_file(b"offsite", SERVICE, APP, target)
        external = str(tmp_path / "elsewhere" / "weidr_keys.json")
        os.makedirs(os.path.dirname(external), exist_ok=True)
        enc.export_key_material(SERVICE, APP, output_path=external)

        # Simulate the machine being lost: no store, no keychain.
        enc.delete_key_store(SERVICE, APP)
        fake_keyring.store.clear()
        enc.clear_key_store_cache()

        with open(external, encoding="utf-8") as handle:
            enc.import_key_material(json.load(handle))
        assert enc.decrypt_data_from_file(target, SERVICE, APP) == b"offsite"


@pytest.mark.skipif(
    enc.KeyEncapsulation is None, reason="oqs not installed; quantum path unavailable"
)
class TestQuantumEncryptorPath:
    """The quantum encryptor is what motivated chunking -- a Kyber768 private
    key is 2400 bytes, nearly 2x the Windows credential blob limit the chunking
    worked around. It stores through the same inherited BaseEncryptor methods,
    so it must behave identically now that the limit no longer applies."""

    def test_key_store_holds_the_quantum_key_unchunked(self, fake_keyring):
        enc.PersonalQuantumEncryptor.generate_and_store_keys(SERVICE, APP)
        store = enc.read_key_store(SERVICE, APP)
        assert store[enc.ENCRYPTOR_TYPE_KEY] == "quantum"
        # Whole key in one value, and nothing chunked into the keychain.
        priv = bytes.fromhex(store[enc.PersonalQuantumEncryptor.ENCRYPTED_PRIV_KEY])
        assert len(priv) > 2000
        assert not [k for _s, k in fake_keyring.sets if k.endswith("__count")]

    def test_quantum_round_trip(self, fake_keyring, tmp_path):
        target = str(tmp_path / "payload.enc")
        enc.PersonalQuantumEncryptor.generate_and_store_keys(SERVICE, APP)
        pub = enc.PersonalQuantumEncryptor.generate_and_store_keys(SERVICE, APP)
        enc.PersonalQuantumEncryptor.encrypt_data(b"quantum payload", pub, target)
        priv = enc.PersonalQuantumEncryptor.load_private_key(SERVICE, APP)
        assert enc.PersonalQuantumEncryptor.decrypt_data_from_file(priv, target) == (
            b"quantum payload"
        )

    def test_quantum_steady_state_touches_one_keychain_item(self, fake_keyring):
        enc.PersonalQuantumEncryptor.generate_and_store_keys(SERVICE, APP)
        enc.clear_key_store_cache()
        fake_keyring.gets.clear()
        enc.PersonalQuantumEncryptor.load_private_key(SERVICE, APP)
        assert fake_keyring.distinct_reads() == {f"{APP}__passphrase"}

    def test_type_mismatch_is_still_detected(self, fake_keyring):
        """A store written by one encryptor must not be read by the other."""
        enc.PersonalQuantumEncryptor.generate_and_store_keys(SERVICE, APP)
        with pytest.raises(ValueError):
            enc.PersonalStandardEncryptor.load_private_key(SERVICE, APP)


class TestPortabilityFallbacks:
    """The module has to work in an application whose Utils lacks these
    helpers -- the case that never arises in this repo, so it is pinned here."""

    def test_host_util_returns_none_for_a_missing_method(self):
        assert enc._host_util("no_such_method_on_utils") is None

    def test_host_util_returns_none_when_utils_is_absent(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "utils.utils", None)
        assert enc._host_util("user_data_dir") is None

    def test_user_data_dir_falls_back_without_utils(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "utils.utils", None)
        assert enc.user_data_dir() == enc._fallback_user_data_dir()

    def test_drives_fall_back_without_utils(self, monkeypatch, tmp_path):
        monkeypatch.setitem(sys.modules, "utils.utils", None)
        monkeypatch.setattr(
            enc, "_fallback_available_external_drives", lambda: [str(tmp_path)]
        )
        assert enc.available_external_drives() == [str(tmp_path)]

    def test_host_implementation_wins_when_present(self, monkeypatch):
        monkeypatch.setattr(
            Utils, "user_data_dir", staticmethod(lambda: "/from/the/host")
        )
        assert enc.user_data_dir() == "/from/the/host"

    def test_fallback_agrees_with_the_host_implementation(self):
        """They encode the same platform conventions; if these diverge, a
        ported app and this one would put keys in different places."""
        assert enc._fallback_user_data_dir() == Utils.user_data_dir()
        assert (
            enc._fallback_available_external_drives()
            == Utils.available_external_drives()
        )

    def test_key_store_path_still_resolves_without_utils(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "utils.utils", None)
        monkeypatch.delenv("SD_RUNNER_CACHE_DIR", raising=False)
        path = enc.key_store_path(SERVICE, APP)
        assert os.path.dirname(path) == os.path.join(
            enc._fallback_user_data_dir(), SERVICE
        )
