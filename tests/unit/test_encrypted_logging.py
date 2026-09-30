"""
The log file is written encrypted, one StreamingLogCipher record per log line.

The record format is shared with the log reader (Protokoll), so the cipher
tests pin behaviour it relies on: records decrypt independently, a truncated
trailing record (a file still being written) ends iteration quietly, and a
wrong key fails loudly rather than yielding garbage.
"""

import io
import logging
import os
import threading
from datetime import datetime, timedelta

import pytest
from cryptography.exceptions import InvalidTag

import lib.logging_setup as logging_setup
from lib.encryptor import (
    StreamingLogCipher,
    encrypt_log_record,
    get_log_cipher_key,
    iter_decrypt_log_file,
)
from lib.logging_setup import (
    LOG_ENCRYPTION_APP_ID,
    LOG_ENCRYPTION_SERVICE,
    LOG_FILE_SUFFIX,
    PLAINTEXT_LOG_FILE_SUFFIX,
    EncryptedFileHandler,
    get_logger,
    set_log_file_encryption,
    set_logger_level,
)


def log_key():
    return get_log_cipher_key(LOG_ENCRYPTION_SERVICE, LOG_ENCRYPTION_APP_ID)


def read_log(path):
    return [r.decode("utf-8") for r in iter_decrypt_log_file(str(path), LOG_ENCRYPTION_SERVICE, LOG_ENCRYPTION_APP_ID)]


def _file_handlers(logger):
    return [h for h in logger.handlers if isinstance(h, (logging.FileHandler, EncryptedFileHandler))]


def logger_with(handler, name):
    logger = logging.getLogger(f"test_encrypted_logging.{name}")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger


# ---------------------------------------------------------------------------
# StreamingLogCipher
# ---------------------------------------------------------------------------

class TestStreamingLogCipher:
    def test_records_round_trip_in_order(self):
        key = log_key()
        stream = io.BytesIO(encrypt_log_record(key, b"one") + encrypt_log_record(key, b"two"))
        assert list(StreamingLogCipher.iter_decrypt(key, stream)) == [b"one", b"two"]

    def test_each_record_gets_its_own_nonce(self):
        key = log_key()
        assert encrypt_log_record(key, b"same") != encrypt_log_record(key, b"same")

    def test_a_truncated_trailing_record_ends_iteration_quietly(self):
        key = log_key()
        data = encrypt_log_record(key, b"whole") + encrypt_log_record(key, b"partial")[:-5]
        assert list(StreamingLogCipher.iter_decrypt(key, io.BytesIO(data))) == [b"whole"]

    def test_a_wrong_key_raises_rather_than_yielding_garbage(self):
        data = encrypt_log_record(log_key(), b"secret")
        with pytest.raises(InvalidTag):
            list(StreamingLogCipher.iter_decrypt(os.urandom(32), io.BytesIO(data)))

    def test_the_key_follows_the_pinned_passphrase(self, monkeypatch):
        """The suite pins it so the handler built at import never reaches a keyring."""
        pinned = log_key()
        monkeypatch.setenv(f"{LOG_ENCRYPTION_SERVICE.upper()}_PASSPHRASE", "something else")
        assert log_key() != pinned


# ---------------------------------------------------------------------------
# EncryptedFileHandler
# ---------------------------------------------------------------------------

class TestEncryptedFileHandler:
    def _handler(self, path):
        handler = EncryptedFileHandler(path, LOG_ENCRYPTION_SERVICE, LOG_ENCRYPTION_APP_ID)
        handler.setFormatter(logging.Formatter("%(message)s"))
        return handler

    def test_each_log_line_is_one_record(self, tmp_path):
        path = tmp_path / f"x{LOG_FILE_SUFFIX}"
        logger = logger_with(self._handler(path), "each_line")
        logger.info("first")
        logger.info("second")
        assert read_log(path) == ["first", "second"]

    def test_nothing_is_written_in_plaintext(self, tmp_path):
        path = tmp_path / f"x{LOG_FILE_SUFFIX}"
        logger_with(self._handler(path), "plaintext").info("a very recognisable message")
        assert b"recognisable" not in path.read_bytes()

    def test_writes_append_to_an_existing_file(self, tmp_path):
        path = tmp_path / f"x{LOG_FILE_SUFFIX}"
        logger_with(self._handler(path), "append_a").info("from a")
        logger_with(self._handler(path), "append_b").info("from b")
        assert read_log(path) == ["from a", "from b"]

    def test_concurrent_writers_leave_every_record_readable(self, tmp_path):
        """Separate handlers stand in for separate processes: each has its own
        lock, so only the OS file lock keeps their records whole."""
        path = tmp_path / f"x{LOG_FILE_SUFFIX}"
        loggers = [logger_with(self._handler(path), f"concurrent_{i}") for i in range(2)]

        def write(logger, n):
            for i in range(50):
                logger.info(f"{n}-{i}-" + "x" * 200)

        threads = [
            threading.Thread(target=write, args=(loggers[n % 2], n)) for n in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(read_log(path)) == 200


# ---------------------------------------------------------------------------
# The project's loggers
# ---------------------------------------------------------------------------

class TestProjectLoggers:
    def test_the_file_handler_is_encrypted(self):
        (handler,) = _file_handlers(get_logger("test_encrypted_logging_a"))
        assert isinstance(handler, EncryptedFileHandler)

    def test_the_file_is_named_log_enc(self):
        (handler,) = _file_handlers(get_logger("test_encrypted_logging_b"))
        assert handler.baseFilename.endswith(LOG_FILE_SUFFIX)

    def test_every_logger_shares_one_handler(self):
        (a,) = _file_handlers(get_logger("test_encrypted_logging_c"))
        (b,) = _file_handlers(get_logger("test_encrypted_logging_d"))
        assert a is b

    def test_a_logged_message_can_be_decrypted_from_the_file(self):
        logger = get_logger("test_encrypted_logging_e")
        (handler,) = _file_handlers(logger)
        marker = f"marker {os.urandom(8).hex()}"
        logger.info(marker)
        assert any(marker in line for line in read_log(handler.baseFilename))

    def test_without_a_key_there_is_no_file_handler(self, monkeypatch, tmp_path, capsys):
        """A plaintext file is not the fallback: it is what encryption prevents."""
        def no_key(*args, **kwargs):
            raise RuntimeError("no keyring")

        # tmp_path itself also holds the isolation fixture's configs/ and cache/.
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.setattr(logging_setup, "_shared_file_handler", None)
        monkeypatch.setattr(logging_setup, "get_log_cipher_key", no_key)
        assert logging_setup._get_file_handler(log_dir / f"x{LOG_FILE_SUFFIX}") is None
        assert "Log file disabled" in capsys.readouterr().err
        assert not list(log_dir.iterdir())

    def test_a_failed_key_is_not_retried_for_each_logger(self, monkeypatch, tmp_path):
        calls = []

        def no_key(*args, **kwargs):
            calls.append(1)
            raise RuntimeError("no keyring")

        monkeypatch.setattr(logging_setup, "_shared_file_handler", None)
        monkeypatch.setattr(logging_setup, "get_log_cipher_key", no_key)
        logging_setup._get_file_handler(tmp_path / "a.log.enc")
        logging_setup._get_file_handler(tmp_path / "b.log.enc")
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# Debug level
# ---------------------------------------------------------------------------

class TestDebugLevel:
    @pytest.fixture(autouse=True)
    def _restore_level(self):
        yield
        set_logger_level(False)

    def test_a_logger_created_after_debug_is_on_logs_debug(self):
        set_logger_level(True)
        logger = get_logger("test_encrypted_logging_level_a")
        assert logger.isEnabledFor(logging.DEBUG)
        assert all(h.level == logging.DEBUG for h in logger.handlers)

    def test_fetching_a_logger_again_keeps_debug(self):
        logger = get_logger("test_encrypted_logging_level_b")
        set_logger_level(True)
        assert get_logger("test_encrypted_logging_level_b").isEnabledFor(logging.DEBUG)


# ---------------------------------------------------------------------------
# Turning encryption off
# ---------------------------------------------------------------------------

@pytest.fixture
def log_dir(monkeypatch, tmp_path):
    """Points new log files at a directory of the test's own. The handler swap
    is process-wide, so afterwards every logger gets the original handler back:
    one re-created inside the test would keep writing into this directory."""
    directory = tmp_path / "logs"
    directory.mkdir()
    original = logging_setup._shared_file_handler

    def log_file_path(encrypted):
        return directory / f"sd_runner_test{LOG_FILE_SUFFIX if encrypted else PLAINTEXT_LOG_FILE_SUFFIX}"

    monkeypatch.setattr(logging_setup, "_log_file_path", log_file_path)
    yield directory

    current = logging_setup._shared_file_handler
    if current is not original:
        for name in list(logging.Logger.manager.loggerDict):
            logger = logging.getLogger(name)
            if current and current in logger.handlers:
                logger.removeHandler(current)
                if original:
                    logger.addHandler(original)
        if current:
            current.close()
    logging_setup._shared_file_handler = original
    logging_setup._encrypt_log_file = True


class TestPlaintextOptOut:
    def test_disabling_writes_a_plaintext_log(self, log_dir):
        set_log_file_encryption(False)
        logger = get_logger("test_encrypted_logging_plain_a")
        marker = f"marker {os.urandom(8).hex()}"
        logger.info(marker)
        (handler,) = _file_handlers(logger)
        assert not isinstance(handler, EncryptedFileHandler)
        handler.flush()
        text = (log_dir / f"sd_runner_test{PLAINTEXT_LOG_FILE_SUFFIX}").read_text(encoding="utf-8")
        assert marker in text

    def test_loggers_created_earlier_are_moved(self, log_dir):
        logger = get_logger("test_encrypted_logging_plain_b")
        (before,) = _file_handlers(logger)
        assert isinstance(before, EncryptedFileHandler)
        set_log_file_encryption(False)
        (after,) = _file_handlers(logger)
        assert not isinstance(after, EncryptedFileHandler)
        assert after is _file_handlers(get_logger("test_encrypted_logging_plain_c"))[0]

    def test_re_enabling_writes_the_encrypted_log(self, log_dir):
        logger = get_logger("test_encrypted_logging_plain_d")
        set_log_file_encryption(False)
        set_log_file_encryption(True)
        (handler,) = _file_handlers(logger)
        assert isinstance(handler, EncryptedFileHandler)
        marker = f"marker {os.urandom(8).hex()}"
        logger.info(marker)
        assert any(marker in line for line in read_log(handler.baseFilename))

    def test_the_handler_level_carries_over(self, log_dir):
        logger = get_logger("test_encrypted_logging_plain_e")
        _file_handlers(logger)[0].setLevel(logging.DEBUG)
        set_log_file_encryption(False)
        assert _file_handlers(logger)[0].level == logging.DEBUG

    def test_an_unchanged_setting_keeps_the_handler(self, log_dir):
        logger = get_logger("test_encrypted_logging_plain_f")
        (before,) = _file_handlers(logger)
        set_log_file_encryption(True)
        assert _file_handlers(logger) == [before]


# ---------------------------------------------------------------------------
# Old-log cleanup
# ---------------------------------------------------------------------------

class TestCleanup:
    def _make(self, directory, days_ago, suffix):
        date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        path = directory / f"sd_runner_{date}{suffix}"
        path.write_bytes(b"")
        return path

    def test_the_date_is_read_from_an_encrypted_log_name(self, tmp_path):
        path = tmp_path / "sd_runner_2026-08-14.log.enc"
        path.write_bytes(b"")
        assert logging_setup._log_file_date(path) == datetime(2026, 8, 14)

    def test_the_date_is_read_from_a_plaintext_log_name(self, tmp_path):
        path = tmp_path / "sd_runner_2026-08-14.log"
        path.write_bytes(b"")
        assert logging_setup._log_file_date(path) == datetime(2026, 8, 14)

    def test_old_encrypted_and_plaintext_logs_are_removed(self, tmp_path):
        old = [self._make(tmp_path, 40 + i, LOG_FILE_SUFFIX) for i in range(6)]
        old += [self._make(tmp_path, 60 + i, ".log") for i in range(6)]
        recent = self._make(tmp_path, 1, LOG_FILE_SUFFIX)
        logging_setup._cleanup_old_logs(tmp_path, logging.getLogger("test_encrypted_logging.cleanup"))
        assert not any(p.exists() for p in old)
        assert recent.exists()
