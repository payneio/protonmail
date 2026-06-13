"""Tests for protonmail tool."""

import subprocess
import sys
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from protonmail.main import (
    extract_email_address,
    generate_email_filename,
    get_sync_dir,
    list_emails_local,
    sanitize_email,
    sanitize_filename,
    search_emails_local,
)


class TestCLI:
    """CLI interface tests."""

    def test_version(self) -> None:
        """--version prints version string."""
        result = subprocess.run(
            [sys.executable, "-m", "protonmail.main", "--version"],
            capture_output=True,
            text=True,
        )
        assert "protonmail" in result.stdout
        assert "0.1.0" in result.stdout

    def test_help(self) -> None:
        """--help shows usage information."""
        result = subprocess.run(
            [sys.executable, "-m", "protonmail.main", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "ProtonMail" in result.stdout


class TestSanitize:
    """Tests for filename sanitization."""

    def test_sanitize_filename_basic(self) -> None:
        """Basic filename sanitization."""
        assert sanitize_filename("hello world") == "hello world"

    def test_sanitize_filename_special_chars(self) -> None:
        """Special characters replaced with underscores."""
        assert sanitize_filename('file<>:"/\\|?*name') == "file_________name"

    def test_sanitize_filename_truncation(self) -> None:
        """Long filenames get truncated."""
        long_name = "x" * 300
        result = sanitize_filename(long_name)
        assert len(result) == 200

    def test_sanitize_email_basic(self) -> None:
        """Email sanitization replaces @."""
        assert sanitize_email("user@domain.com") == "user_domain.com"

    def test_sanitize_email_special(self) -> None:
        """Email with angle brackets cleaned."""
        assert sanitize_email("<user@domain.com>") == "user_domain.com"


class TestExtractEmail:
    """Tests for email address extraction."""

    def test_angle_brackets(self) -> None:
        """Extract email from angle brackets."""
        assert extract_email_address("Name <user@example.com>") == "user@example.com"

    def test_plain_email(self) -> None:
        """Extract plain email address."""
        assert extract_email_address("user@example.com") == "user@example.com"

    def test_no_email(self) -> None:
        """Return trimmed string when no email present."""
        assert extract_email_address("unknown") == "unknown"


class TestGenerateFilename:
    """Tests for email filename generation."""

    def test_basic_filename(self) -> None:
        """Generate filename from message headers."""
        msg = Message()
        msg["Date"] = "Thu, 17 Jul 2024 01:14:40 +0000"
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Test Subject"

        filename = generate_email_filename(msg)
        assert filename.startswith("2024-07-17_01-14-40_from_sender_example.com_to_recipient_example.com_")
        assert filename.endswith(".eml")
        assert "Test Subject" in filename

    def test_missing_date(self) -> None:
        """Handle missing date gracefully."""
        msg = Message()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"

        filename = generate_email_filename(msg)
        assert "unknown-date" in filename

    def test_length_limit(self) -> None:
        """Filename respects max_length."""
        msg = Message()
        msg["Date"] = "Thu, 17 Jul 2024 01:14:40 +0000"
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "x" * 300

        filename = generate_email_filename(msg, max_length=255)
        assert len(filename) <= 255


class TestGetSyncDir:
    """Tests for sync directory resolution."""

    def test_protonmail_data_dir_env(self) -> None:
        """PROTONMAIL_DATA_DIR takes priority."""
        with patch.dict("os.environ", {"PROTONMAIL_DATA_DIR": "/custom/path"}):
            assert get_sync_dir() == Path("/custom/path")

    def test_ddata_fallback(self) -> None:
        """Falls back to DDATA when PROTONMAIL_DATA_DIR not set."""
        env = {"DDATA": "/mydata"}
        with patch.dict("os.environ", env, clear=True):
            assert get_sync_dir() == Path("/mydata/messages/email/protonmail")

    def test_default(self) -> None:
        """Default path when no env vars set."""
        with patch.dict("os.environ", {}, clear=True):
            assert get_sync_dir() == Path("/data/messages/email/protonmail")


class TestListEmailsLocal:
    """Tests for local email listing."""

    def test_missing_cache(self, tmp_path: Path) -> None:
        """Returns False when cache doesn't exist."""
        with patch("protonmail.main.get_sync_dir", return_value=tmp_path / "nope"):
            assert list_emails_local() is False

    def test_empty_folder(self, tmp_path: Path) -> None:
        """Shows message when folder is empty."""
        inbox = tmp_path / "INBOX"
        inbox.mkdir()
        with patch("protonmail.main.get_sync_dir", return_value=tmp_path):
            assert list_emails_local() is True

    def test_lists_eml_files(self, tmp_path: Path) -> None:
        """Lists .eml files from cache."""
        inbox = tmp_path / "INBOX"
        inbox.mkdir()
        eml_content = b"From: test@example.com\nSubject: Hello\nDate: Thu, 1 Jan 2024 00:00:00 +0000\n\nBody"
        (inbox / "test.eml").write_bytes(eml_content)

        with patch("protonmail.main.get_sync_dir", return_value=tmp_path):
            assert list_emails_local() is True


class TestSearchEmailsLocal:
    """Tests for local email search."""

    def test_missing_cache(self, tmp_path: Path) -> None:
        """Returns False when cache doesn't exist."""
        with patch("protonmail.main.get_sync_dir", return_value=tmp_path / "nope"):
            assert search_emails_local("test") is False

    def test_finds_matching_email(self, tmp_path: Path) -> None:
        """Finds emails matching query."""
        inbox = tmp_path / "INBOX"
        inbox.mkdir()
        eml_content = b"From: test@example.com\nSubject: Invoice 123\nDate: Thu, 1 Jan 2024 00:00:00 +0000\n\nBody"
        (inbox / "test.eml").write_bytes(eml_content)

        with patch("protonmail.main.get_sync_dir", return_value=tmp_path):
            assert search_emails_local("invoice") is True

    def test_no_match(self, tmp_path: Path) -> None:
        """Returns True but prints nothing when no match."""
        inbox = tmp_path / "INBOX"
        inbox.mkdir()
        eml_content = b"From: test@example.com\nSubject: Hello\nDate: Thu, 1 Jan 2024 00:00:00 +0000\n\nBody"
        (inbox / "test.eml").write_bytes(eml_content)

        with patch("protonmail.main.get_sync_dir", return_value=tmp_path):
            assert search_emails_local("nonexistent") is True
