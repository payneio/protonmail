#!/usr/bin/env python3
"""protonmail: Access and manage ProtonMail emails via Bridge.

Access your ProtonMail inbox through the ProtonMail Bridge using IMAP/SMTP.
All commands now work with local cached .eml files for fast, offline access.
Run 'protonmail sync' first to download emails locally.

Usage: protonmail [options] [command]

Commands:
  sync               Sync all emails to local .eml files
  list [folder]       List emails (default: INBOX, uses local cache)
  read <filename>     Read a specific email by filename (uses local cache)
  send               Send a new email (interactive, requires IMAP)
  search <query>     Search emails by subject or sender (uses local cache)

Examples:
  protonmail sync                        # Sync all emails
  protonmail sync -o ~/emails            # Sync to custom directory
  protonmail list                        # List emails in INBOX from local cache
  protonmail list Sent                   # List emails in Sent folder
  protonmail read "2024-07-17_01-14-40_from_..._.eml"
  protonmail search "invoice"            # Search by subject or sender
"""

import argparse
import email
import imaplib
import os
import re
import smtplib
import sys
from email.message import EmailMessage, Message
from email.utils import formatdate, make_msgid, parsedate_to_datetime
from pathlib import Path
from typing import Any

from protonmail import __version__

__all__ = ["main"]


def load_config() -> dict[str, Any]:
    """Load configuration from environment variables."""
    username = os.environ.get("PROTONMAIL_USERNAME", "")
    if not username:
        print(
            "Error: PROTONMAIL_USERNAME environment variable not set", file=sys.stderr
        )
        sys.exit(1)

    api_key = os.environ.get("PROTONMAIL_API_KEY", "")
    if not api_key:
        print("Error: PROTONMAIL_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    config: dict[str, Any] = {
        "IMAP": {
            "hostname": "127.0.0.1",
            "port": 1143,
            "username": username,
            "password": api_key,
            "security": "STARTTLS",
        },
        "SMTP": {
            "hostname": "127.0.0.1",
            "port": 1025,
            "username": username,
            "password": api_key,
            "security": "STARTTLS",
        },
    }

    return config


def connect_imap(config: dict[str, Any]) -> imaplib.IMAP4:
    """Connect to IMAP server."""
    imap_config = config["IMAP"]

    if imap_config["security"] == "SSL/TLS":
        imap = imaplib.IMAP4_SSL(imap_config["hostname"], imap_config["port"])
    else:
        imap = imaplib.IMAP4(imap_config["hostname"], imap_config["port"])
        if imap_config["security"] == "STARTTLS":
            imap.starttls()

    imap.login(imap_config["username"], imap_config["password"])
    return imap


def list_folders(imap: imaplib.IMAP4) -> list[str]:
    """List all available folders."""
    status, folders = imap.list()
    if status != "OK":
        return []

    folder_list: list[str] = []
    for folder in folders:
        if isinstance(folder, bytes):
            folder_str = folder.decode()
        else:
            folder_str = str(folder)
        folder_parts = folder_str.split(' "/"')
        if len(folder_parts) > 1:
            folder_name = folder_parts[-1].strip().strip('"')
            folder_list.append(folder_name)

    return folder_list


def get_sync_dir() -> Path:
    """Get the sync directory path.

    Checks PROTONMAIL_DATA_DIR first (set by castle), then DDATA fallback.
    """
    data_dir = os.environ.get("PROTONMAIL_DATA_DIR")
    if data_dir:
        return Path(data_dir)
    ddata = os.environ.get("DDATA", "/data")
    return Path(f"{ddata}/messages/email/protonmail")


def sanitize_filename(filename: str) -> str:
    """Sanitize a string to be used as a filename."""
    filename = re.sub(r'[<>:"/\\|?*]', "_", filename)
    filename = re.sub(r"[\x00-\x1f\x7f]", "", filename)
    if len(filename) > 200:
        filename = filename[:200]
    return filename.strip()


def sanitize_email(email_addr: str) -> str:
    """Sanitize email address for use in filename."""
    email_addr = email_addr.replace("@", "_")
    email_addr = re.sub(r'[<>"\']', "", email_addr)
    email_addr = re.sub(r"[/\\:*?|]", "_", email_addr)
    return email_addr.strip()


def extract_email_address(email_field: str) -> str:
    """Extract just the email address from a field like 'Name <email@domain.com>'."""
    match = re.search(r"<([^>]+)>", email_field)
    if match:
        return match.group(1)
    if "@" in email_field:
        return email_field.strip().strip("\"'")
    return email_field.strip()


def generate_email_filename(msg: Message, max_length: int = 255) -> str:
    """Generate filename in format: YYYY-MM-DD_HH-MM-SS_from_FROM_to_TO_SUBJECT.eml."""
    msg_date = msg.get("Date", "")
    try:
        date_obj = parsedate_to_datetime(msg_date)
        date_str = date_obj.strftime("%Y-%m-%d_%H-%M-%S")
    except (TypeError, ValueError):
        date_str = "unknown-date"

    from_field = msg.get("From", "unknown")
    from_email = extract_email_address(from_field)
    from_safe = sanitize_email(from_email)

    to_field = msg.get("To", "unknown")
    if "," in to_field:
        to_field = to_field.split(",")[0]
    to_email = extract_email_address(to_field)
    to_safe = sanitize_email(to_email)

    subject = msg.get("Subject", "no-subject")
    subject_safe = sanitize_filename(subject)

    prefix = f"{date_str}_from_{from_safe}_to_{to_safe}_"
    suffix = ".eml"
    available_length = max_length - len(prefix) - len(suffix)

    if len(subject_safe) > available_length:
        subject_safe = subject_safe[:available_length]

    return f"{prefix}{subject_safe}{suffix}"


def list_emails_local(folder: str = "INBOX", limit: int = 20) -> bool:
    """List emails from local cache. Returns True if successful."""
    try:
        sync_dir = get_sync_dir()
        if not sync_dir.exists():
            return False

        safe_folder = sanitize_filename(folder)
        folder_path = sync_dir / safe_folder

        if not folder_path.exists():
            print(f"Folder '{folder}' not found in local cache", file=sys.stderr)
            return False

        eml_files = list(folder_path.glob("*.eml"))
        if not eml_files:
            print(f"No emails found in folder '{folder}'")
            return True

        eml_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        eml_files = eml_files[:limit]

        print(
            f"\nEmails in {folder} (showing last {len(eml_files)} from local cache):\n"
        )

        for eml_file in eml_files:
            try:
                with open(eml_file, "rb") as f:
                    msg = email.message_from_bytes(f.read())

                date = msg.get("Date", "No date")
                from_addr = msg.get("From", "No sender")
                subject = msg.get("Subject", "No subject")

                print(f"File: {eml_file.name}")
                print(f"  Date: {date}")
                print(f"  From: {from_addr}")
                print(f"  Subject: {subject}")
                print()
            except Exception:
                continue

        return True

    except Exception as e:
        print(f"Error reading local cache: {e}", file=sys.stderr)
        return False


def list_emails(folder: str = "INBOX", limit: int = 20) -> None:
    """List emails in the specified folder from local cache."""
    if not list_emails_local(folder, limit):
        print(
            "\nLocal cache not available. Run 'protonmail sync' first to download emails.",
            file=sys.stderr,
        )
        sys.exit(1)


def read_email_local(filename: str) -> bool:
    """Read an email from local cache by filename. Returns True if successful."""
    try:
        sync_dir = get_sync_dir()
        if not sync_dir.exists():
            return False

        eml_file = None
        for folder_path in sync_dir.iterdir():
            if folder_path.is_dir():
                potential_file = folder_path / filename
                if potential_file.exists():
                    eml_file = potential_file
                    break

        if not eml_file:
            print(f"Email file '{filename}' not found in local cache", file=sys.stderr)
            return False

        with open(eml_file, "rb") as f:
            msg = email.message_from_bytes(f.read())

        print(f"\nFrom: {msg.get('From', 'Unknown')}")
        print(f"To: {msg.get('To', 'Unknown')}")
        print(f"Subject: {msg.get('Subject', 'No subject')}")
        print(f"Date: {msg.get('Date', 'Unknown')}")
        print("\n" + "=" * 70 + "\n")

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        body = payload.decode("utf-8", errors="ignore")
                    break
        else:
            payload = msg.get_payload(decode=True)
            if payload and isinstance(payload, bytes):
                body = payload.decode("utf-8", errors="ignore")

        print(body)
        print()

        return True

    except Exception as e:
        print(f"Error reading email from local cache: {e}", file=sys.stderr)
        return False


def read_email(filename: str) -> None:
    """Read a specific email by filename from local cache."""
    if not read_email_local(filename):
        print(
            "\nLocal cache not available. Run 'protonmail sync' first to download emails.",
            file=sys.stderr,
        )
        sys.exit(1)


def search_emails_local(query: str, folder: str = "INBOX") -> bool:
    """Search emails in local cache by subject or sender. Returns True if successful."""
    try:
        sync_dir = get_sync_dir()
        if not sync_dir.exists():
            return False

        safe_folder = sanitize_filename(folder)
        folder_path = sync_dir / safe_folder

        if not folder_path.exists():
            print(f"Folder '{folder}' not found in local cache", file=sys.stderr)
            return False

        matches: list[tuple[Path, Message]] = []
        query_lower = query.lower()

        for eml_file in folder_path.glob("*.eml"):
            try:
                with open(eml_file, "rb") as f:
                    msg = email.message_from_bytes(f.read())

                subject = msg.get("Subject", "").lower()
                from_addr = msg.get("From", "").lower()

                if query_lower in subject or query_lower in from_addr:
                    matches.append((eml_file, msg))
            except Exception:
                continue

        if not matches:
            print(f"No emails found matching '{query}'")
            return True

        print(
            f"\nFound {len(matches)} email(s) matching '{query}' (from local cache):\n"
        )

        matches.sort(key=lambda x: x[0].stat().st_mtime, reverse=True)

        for eml_file, msg in matches:
            date = msg.get("Date", "No date")
            from_addr = msg.get("From", "No sender")
            subject = msg.get("Subject", "No subject")

            print(f"File: {eml_file.name}")
            print(f"  Date: {date}")
            print(f"  From: {from_addr}")
            print(f"  Subject: {subject}")
            print()

        return True

    except Exception as e:
        print(f"Error searching local cache: {e}", file=sys.stderr)
        return False


def search_emails(query: str, folder: str = "INBOX") -> None:
    """Search emails by subject or sender in local cache."""
    if not search_emails_local(query, folder):
        print(
            "\nLocal cache not available. Run 'protonmail sync' first to download emails.",
            file=sys.stderr,
        )
        sys.exit(1)


def send_email(config: dict[str, Any]) -> None:
    """Send a new email interactively."""
    try:
        to_email = input("To: ")
        subject = input("Subject: ")

        body_lines: list[str] = []
        while True:
            try:
                line = input()
                if line == ".":
                    break
                body_lines.append(line)
            except EOFError:
                break

        body = "\n".join(body_lines)

        msg = EmailMessage()
        msg["From"] = config["SMTP"]["username"]
        msg["To"] = to_email
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=config["SMTP"]["username"].split("@")[-1])
        msg.set_content(body)

        smtp_config = config["SMTP"]
        if smtp_config["security"] == "SSL/TLS":
            smtp = smtplib.SMTP_SSL(smtp_config["hostname"], smtp_config["port"])
        else:
            smtp = smtplib.SMTP(smtp_config["hostname"], smtp_config["port"])
            if smtp_config["security"] == "STARTTLS":
                smtp.starttls()

        smtp.login(smtp_config["username"], smtp_config["password"])
        smtp.send_message(msg)
        smtp.quit()

        print(f"\nEmail sent successfully to {to_email}")

    except (smtplib.SMTPException, OSError, EOFError) as e:
        print(f"Error sending email: {e}", file=sys.stderr)
        sys.exit(1)


def sync_emails(config: dict[str, Any], output_dir: str | None = None) -> None:
    """Sync all emails from ProtonMail to local .eml files."""
    try:
        if output_dir is None:
            output_path = get_sync_dir()
        else:
            output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        imap = connect_imap(config)

        folders = list_folders(imap)
        if not folders:
            folders = ["INBOX"]

        print(f"Syncing emails from {len(folders)} folder(s) to {output_path}\n")

        total_synced = 0
        total_skipped = 0

        for folder in folders:
            safe_folder = sanitize_filename(folder)
            folder_path = output_path / safe_folder
            folder_path.mkdir(exist_ok=True)

            status, data = imap.select(f'"{folder}"' if " " in folder else folder)
            if status != "OK":
                print(f"Warning: Could not access folder '{folder}', skipping...")
                continue

            status, data = imap.search(None, "ALL")
            if status != "OK":
                print(f"Warning: Could not search folder '{folder}', skipping...")
                continue

            message_ids = data[0].split()
            if not message_ids:
                print(f"  {folder}: No messages")
                continue

            print(f"  {folder}: Processing {len(message_ids)} message(s)...")

            synced = 0
            skipped = 0

            existing_message_ids: set[str] = set()
            for existing_file in folder_path.glob("*.eml"):
                try:
                    with open(existing_file, "rb") as f:
                        existing_msg = email.message_from_bytes(f.read())
                        existing_msg_id = existing_msg.get("Message-ID", "")
                        if existing_msg_id:
                            existing_message_ids.add(existing_msg_id)
                except Exception:
                    pass

            for msg_id in message_ids:
                try:
                    status, data = imap.fetch(msg_id, "(RFC822)")
                    if status != "OK" or not data or not data[0]:
                        continue

                    raw_email = data[0][1]
                    if not isinstance(raw_email, bytes):
                        continue
                    msg = email.message_from_bytes(raw_email)

                    msg_message_id = msg.get("Message-ID", "")
                    if msg_message_id and msg_message_id in existing_message_ids:
                        skipped += 1
                        continue

                    filename = generate_email_filename(msg)
                    filepath = folder_path / filename

                    with open(filepath, "wb") as f:
                        f.write(raw_email)

                    synced += 1
                    if msg_message_id:
                        existing_message_ids.add(msg_message_id)

                except Exception as e:
                    print(
                        f"    Warning: Error processing message {msg_id.decode()}: {e}"
                    )
                    continue

            print(f"    Synced: {synced} new, {skipped} already existed")
            total_synced += synced
            total_skipped += skipped

        imap.logout()

        print("\nSync complete!")
        print(f"  Total new emails synced: {total_synced}")
        print(f"  Total emails skipped (already existed): {total_skipped}")
        print(f"  Output directory: {output_path}")

    except (imaplib.IMAP4.error, OSError, ValueError) as e:
        print(f"Error syncing emails: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> int:
    """Run the protonmail CLI."""
    parser = argparse.ArgumentParser(
        description="Access and manage ProtonMail emails via Bridge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--version", action="version", version=f"protonmail {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # List command
    list_parser = subparsers.add_parser("list", help="List emails")
    list_parser.add_argument(
        "folder",
        nargs="?",
        default="INBOX",
        help="Folder to list (default: INBOX)",
    )
    list_parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=20,
        help="Number of emails to show (default: 20)",
    )

    # Read command
    read_parser = subparsers.add_parser("read", help="Read an email")
    read_parser.add_argument("message_id", help="ID of the message to read")

    # Search command
    search_parser = subparsers.add_parser("search", help="Search for emails")
    search_parser.add_argument("query", help="Search term (subject or sender)")
    search_parser.add_argument(
        "-f",
        "--folder",
        default="INBOX",
        help="Folder to search (default: INBOX)",
    )

    # Send command
    subparsers.add_parser("send", help="Send a new email (interactive)")

    # Sync command
    sync_parser = subparsers.add_parser(
        "sync", help="Sync all emails to local .eml files"
    )
    sync_parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output directory (default: PROTONMAIL_DATA_DIR or /data/messages/email/protonmail)",
    )

    args = parser.parse_args()

    if args.command == "list":
        list_emails(args.folder, args.limit)
    elif args.command == "read":
        read_email(args.message_id)
    elif args.command == "search":
        search_emails(args.query, args.folder)
    elif args.command == "send":
        send_email(load_config())
    elif args.command == "sync":
        sync_emails(load_config(), args.output)
    else:
        list_emails()

    return 0


if __name__ == "__main__":
    sys.exit(main())
