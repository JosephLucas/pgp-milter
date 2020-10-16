# -*- coding: utf-8 -*-
#
# tests for the `pgp` module.
#
import re
import gnupg
from email.mime.text import MIMEText
from email.message import Message
from email.parser import Parser
from email.policy import default as default_policy
from pgp_milter import pgp


# PGP fingerprints
FPR_ALICE = "FC576D66A075141F41770B15F028476ACE63FE41"
FPR_ALICE2 = "BC8E0FFE80B27CAB91D6D2315B1D44F70BA91072"
FPR_ALICE3 = "CB0374057FD3EEC52D39B467524AE6A48F5EB464"
FPR_BOB = "FDBE48E6FE58D021A5C8BE3B982AD46FA8789D5C"


def replace_pgp_msg(text):
    # helper to remove pgp messages out of MIME containers.
    # pgp messages differ from each other when generated, even if they encrypt
    # the same message.
    return re.sub(
        "-----BEGIN PGP MESSAGE-----\n\n(.+?)-----END PGP MESSAGE-----",
        (
            "-----BEGIN PGP MESSAGE-----\n\n"
            "<PGP STUFF>\n\n-----END PGP MESSAGE-----"
        ),
        text,
        flags=re.M + re.S,
    )


def test_parse_raw(tpath):
    # we can turn raw messages into Message objects
    headers = [
        (b"Return-Path", b"<lauren@foobar.com>"),
        (
            b"Received",
            b"from foobar.com (localhost [127.0.0.1])"
            b"\n	by hemholt.foobar.com (8.9.3/8.8.7) with ESMTP id SAA03001;"
            b"\n	Mon, 29 Jan 2001 18:08:41 -0500",
        ),
        (b"Sender", b"lauren@foobar.com"),
        (b"Message-ID", b"<3A75F7F6.CBF9E75@foobar.com>"),
        (b"Date", b"Mon, 29 Jan 2001 18:08:39 -0500"),
        (b"From", b"Lauren Hemholz <lauren@foobar.com>"),
        (b"Organization", b"Hemholtz Family"),
        (b"X-Mailer", b"Mozilla 4.76 [en] (X11; U; Linux 2.2.16-3 i586)"),
        (b"X-Accept-Language", b"en"),
        (b"MIME-Version", b"1.0"),
        (b"To", b"Jriser13@aol.com"),
        (b"Subject", b"Re: P.B.S kids"),
        (b"References", b"<e4.1045e74c.27a7018b@aol.com>"),
        (
            b"Content-Type",
            b"multipart/alternative;"
            b'\n boundary="------------7EC2082FC4F651D73FCD6FE1"',
        ),
        (b"Status", b"O"),
    ]
    body = (tpath / "samples/full-mail01").read_bytes().split(b"\n\n\n")[-1]
    parsed = pgp.parse_raw(headers, body)
    assert isinstance(parsed, Message)


def test_gpg_encrypt(tmpdir, tpath):
    # we can pgp encrypt text
    gpg = gnupg.GPG(gnupghome=str(tmpdir))
    ascii_key = (tpath / "alice.pub").read_text()
    gpg.import_keys(ascii_key)
    msg = pgp.gpg_encrypt(gpg, "meet me at dawn", FPR_ALICE)
    assert str(msg).startswith("-----BEGIN PGP MESSAGE-----")
    assert len(str(msg)) < 1000


def test_gpg_encrypt_multiple_recipients(tmpdir, tpath):
    # we can encrypt for several recipients in a row
    gpg = gnupg.GPG(gnupghome=str(tmpdir))
    ascii_key1 = (tpath / "alice.pub").read_text()
    ascii_key2 = (tpath / "bob.pub").read_text()
    gpg.import_keys(ascii_key1 + ascii_key2)
    msg = pgp.gpg_encrypt(gpg, "meet me at dawn", [FPR_ALICE, FPR_BOB])
    assert str(msg).startswith("-----BEGIN PGP MESSAGE-----")
    assert len(str(msg)) >= 1000


def test_pgp_mime_encrypt(tmpdir, tpath):
    # we can create PGP-MIME messages from MIME
    gpg = gnupg.GPG(gnupghome=str(tmpdir))
    gpg.import_keys((tpath / "alice.pub").read_text())
    mime_msg = MIMEText(_text="meet me at dawn")
    result = pgp.pgp_mime_encrypt(gpg, mime_msg, FPR_ALICE)
    result.set_boundary("===============1111111111111111111==")
    expected = replace_pgp_msg(
        (tpath / "samples/mime-enc-body").read_text()
    )
    assert replace_pgp_msg(result.as_string()) == expected


def test_pgp_mime_encrypt_fullmail(tmpdir, tpath):
    # we can encrypt a complete message
    gpg = gnupg.GPG(gnupghome=str(tmpdir))
    gpg.import_keys((tpath / "alice.pub").read_text())
    with (tpath / "samples/full-mail02").open() as fp:
        msg = Parser(policy=default_policy).parse(fp)
    result = pgp.pgp_mime_encrypt(gpg, msg, FPR_ALICE)
    assert result.keys() == [
        "Return-Path", "Received", "Date", "From", "To", "Subject",
        "Message-ID", "User-Agent", "Content-Type", "MIME-Version",
        "Content-Disposition"]
    assert "multipart/encrypted" in result.as_string()
    assert "BEGIN PGP MESSAGE" in result.as_string()


def test_get_encryptable_payload(tpath):
    # we can extract the encryptable part of a message
    with (tpath / "samples/full-mail02").open("r") as fp:
        msg = Parser(policy=default_policy).parse(fp)
    result = pgp.get_encryptable_payload(msg)
    want = (tpath / "samples/payload02").read_text()
    assert result.as_string() == want


def test_prepend_headerfields():
    # we can inject headerfields
    msg = Parser(policy=default_policy).parsestr(
        "To: foo\nSubject: bar\n\nMeet at dawni\n")
    msg.add_header("X-Foo", "baz")
    result = pgp.prepend_header_fields(msg, [("To", "foo"), ("From", "bar")])
    assert result.keys() == ["From", "To", "Subject", "X-Foo"]


def test_get_fingerprints_no_match(tmpdir):
    # we find only existing fingerprints
    gpg = gnupg.GPG(gnupghome=str(tmpdir))
    result1 = pgp.get_fingerprints(gpg, ["alice@sample.net", "bob@sample.org"])
    assert result1 == []


def test_get_fingerprints_one_match(tmpdir):
    # we find a fingerprint, if it is stored
    gpg = gnupg.GPG(gnupghome=str(tmpdir))
    gpg.import_keys(open("tests/alice.pub", "r").read())
    result1 = pgp.get_fingerprints(gpg, ["alice@sample.net", "bob@sample.org"])
    assert result1 == [FPR_ALICE]


def test_get_fingerprints_string_input(tmpdir):
    # we find a fingerprint also if we pass it as string
    # and not a list of strings
    gpg = gnupg.GPG(gnupghome=str(tmpdir))
    gpg.import_keys(open("tests/alice.pub", "r").read())
    result1 = pgp.get_fingerprints(gpg, "alice@sample.net")
    assert result1 == [FPR_ALICE]


def test_get_fingerprints_overlapping_names(tmpdir):
    # we only find exactly matching fingerprints
    gpg = gnupg.GPG(gnupghome=str(tmpdir))
    # the key of "alice@sample.net"
    gpg.import_keys(open("tests/alice.pub", "r").read())
    # this is the key of "thealice@sample.net"
    gpg.import_keys(open("tests/alice2.pub", "r").read())
    assert [FPR_ALICE] == pgp.get_fingerprints(gpg, "alice@sample.net")
    assert [FPR_ALICE2] == pgp.get_fingerprints(gpg, "thealice@sample.net")


def test_get_fingerprints_matching_names(tmpdir):
    # in case of keys with matching UIDs we take the newest one.
    gpg = gnupg.GPG(gnupghome=str(tmpdir))
    # the older key of "alice@sample.net"
    gpg.import_keys(open("tests/alice.pub", "r").read())
    # this is a newer key of "alice@sample.net"
    gpg.import_keys(open("tests/alice3.pub", "r").read())
    assert [FPR_ALICE3] == pgp.get_fingerprints(gpg, "alice@sample.net")


def test_encrypt_msg(tmpdir):
    # we can encrypt a message
    gpg = gnupg.GPG(gnupghome=str(tmpdir))
    gpg.import_keys(open("tests/alice.pub", "r").read())
    fp = open("tests/samples/full-mail02", "r")
    msg = Parser(policy=default_policy).parse(fp)
    result = pgp.encrypt_msg(msg, ["alice@sample.net"], str(tmpdir))
    assert result[0] == True
    enc_msg = result[1].as_string()
    assert "-----BEGIN PGP MESSAGE-----" in enc_msg
