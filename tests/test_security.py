"""Security tests. The archive is a third party; its response is not trusted.

Nothing here needs a network -- the archive bytes are constructed in the test,
which is the only way to exercise a hostile response deliberately.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beurs.bhavcopy import MAX_UNPACKED, Unavailable, Untrusted, _read_zip


def _zip(name: str, payload: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, payload)
    return buf.getvalue()


def test_a_valid_archive_is_read():
    data = _zip("cm01JAN2024bhav.csv", b"SYMBOL,SERIES\nRELIANCE,EQ\n")
    df = _read_zip(data)
    assert list(df.columns) == ["SYMBOL", "SERIES"]
    assert df.iloc[0]["SYMBOL"] == "RELIANCE"


def test_a_decompression_bomb_is_refused_before_it_is_expanded():
    """Highly compressible payloads let a small download declare a huge
    expansion. The declared size is checked first, so the bomb is never read."""
    bomb = _zip("bomb.csv", b"0" * (MAX_UNPACKED + 1024))
    assert len(bomb) < 1_000_000, "the point is that it is small on the wire"
    with pytest.raises(Untrusted, match="unpacked"):
        _read_zip(bomb)


def test_an_html_error_page_is_refused_rather_than_parsed():
    """The archive answers 200 with HTML instead of a 4xx, so a status check is
    not enough -- this is what actually arrives when a file is absent."""
    with pytest.raises(Untrusted, match="not a zip"):
        _read_zip(b"<!DOCTYPE html><html><body>Not found</body></html>")


def test_an_empty_archive_is_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("adir/", b"")
    with pytest.raises(Untrusted, match="no files"):
        _read_zip(buf.getvalue())


def test_an_oversized_download_is_refused_without_parsing():
    with pytest.raises(Untrusted, match="over the"):
        _read_zip(b"x" * (64 * 1024 * 1024 + 1))


def test_a_traversing_member_name_cannot_write_anywhere(tmp_path):
    """Nothing is extracted to disk, so a ../ name is inert. Pinned so a future
    refactor to extractall() fails this test instead of shipping."""
    data = _zip("../../../../tmp/evil.csv", b"SYMBOL\nX\n")
    df = _read_zip(data)
    assert list(df.columns) == ["SYMBOL"]
    assert not (tmp_path / "evil.csv").exists()
    assert not Path("/tmp/evil.csv").exists()


def test_untrusted_is_catchable_as_unavailable():
    """Existing callers catch Unavailable; they must keep working."""
    assert issubclass(Untrusted, Unavailable)
