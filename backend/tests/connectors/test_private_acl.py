"""Live Windows owner-only ACL enforcement (D4-05). No mocks, no skips on this host.

Every ACL test here calls the real ``advapi32`` security APIs against real temp paths: the
module under test and these fixtures both go through ``SetSecurityInfo``/``GetNamedSecurityInfo``
so a pass is evidence, not an assertion about a stub. The only monkeypatching is of the
platform flag, which proves the fail-closed branch for a non-Windows host.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md section 5, docs/SECURITY_PRIVACY.md class B.
"""

import ctypes
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from probation.connectors import acl as acl_mod
from probation.connectors.acl import (
    AclUnsupported,
    PrivatePathRejected,
    apply_owner_only,
    current_user_sid_text,
    verify_owner_only,
)
from probation.connectors.types import ConnectorError

_VP = ctypes.c_void_p
_PP = ctypes.POINTER(_VP)
_U32 = ctypes.c_ulong
_I32 = ctypes.c_int
_BOOL = ctypes.c_int
_WSTR = ctypes.c_wchar_p

SE_FILE_OBJECT = 1
_OWNER_SI = 0x00000001
_DACL_SI = 0x00000004
_PROTECTED_DACL_SI = 0x80000000
_FILE_ALL_ACCESS = 0x1F01FF
_SET_ACCESS = 2
_TRUSTEE_IS_SID = 0
_TRUSTEE_IS_UNKNOWN = 0
_WRITE_DAC = 0x00040000
_WRITE_OWNER = 0x00080000
_READ_CONTROL = 0x00020000
_OPEN_EXISTING = 3
_NORMAL = 0x00000080
_BACKUP_SEMANTIC = 0x02000000
_INVALID_HANDLE = 0xFFFFFFFFFFFFFFFF

EVERYONE = "S-1-1-0"
BUILTIN_USERS = "S-1-5-32-545"
OBJECT_AND_CONTAINER_INHERIT = 0x00000003
CANARY = "CANARY-TOKEN-NEVER-IN-AN-ERROR-string"

requires_windows = pytest.mark.skipif(
    not acl_mod.IS_WINDOWS,
    reason="host must be the Windows target of this connector; always false on this machine",
)


class _Trustee(ctypes.Structure):
    _fields_ = [
        ("pMultipleTrustee", _PP),
        ("MultipleTrusteeOperation", _U32),
        ("TrusteeType", _U32),
        ("TrusteeForm", _U32),
        ("Name", _VP),
    ]


class _Explicit(ctypes.Structure):
    _fields_ = [
        ("grfAccessPermissions", _U32),
        ("grfAccessMode", _U32),
        ("grfInheritance", _U32),
        ("Trustee", _Trustee),
    ]


def _advapi() -> ctypes.WinDLL:
    return ctypes.WinDLL("advapi32", use_last_error=True)


def _kernel32() -> ctypes.WinDLL:
    return ctypes.WinDLL("kernel32", use_last_error=True)


@pytest.fixture
def private_dir(tmp_path: Path) -> Iterator[Path]:
    """A private root that is genuinely owner-only before any test body runs."""
    root = tmp_path / "private"
    root.mkdir()
    apply_owner_only(root, is_dir=True)
    yield root


def _sid_of(text: str) -> _VP:
    advapi = _advapi()
    convert = advapi.ConvertStringSidToSidW
    convert.restype = _BOOL
    convert.argtypes = [_WSTR, _PP]
    sid = _VP()
    if not convert(text, ctypes.byref(sid)):
        raise AssertionError(f"fixture_sid_unavailable_{text}")
    return sid


def _free(*pointers: ctypes.c_void_p) -> None:
    local_free = _kernel32().LocalFree
    local_free.restype = _VP
    local_free.argtypes = [_VP]
    for pointer in pointers:
        if pointer.value:
            local_free(pointer)


def _write_dacl(path: Path, entries: list[tuple[ctypes.c_void_p, int]], *, is_dir: bool) -> None:
    """Replace the DACL with exactly these full-control allow ACEs. Fixture-only."""
    advapi = _advapi()
    kernel32 = _kernel32()
    if not entries:
        raise AssertionError("fixture needs at least one ace")
    array = (_Explicit * len(entries))()
    for index, (sid, inheritance) in enumerate(entries):
        request = array[index]
        request.grfAccessPermissions = _FILE_ALL_ACCESS
        request.grfAccessMode = _SET_ACCESS
        request.grfInheritance = inheritance
        request.Trustee.TrusteeType = _TRUSTEE_IS_UNKNOWN
        request.Trustee.TrusteeForm = _TRUSTEE_IS_SID
        request.Trustee.Name = sid
    set_entries = advapi.SetEntriesInAclW
    set_entries.restype = _U32
    set_entries.argtypes = [_U32, _VP, _VP, _PP]
    new_dacl = _VP()
    assert set_entries(len(entries), ctypes.byref(array), None, ctypes.byref(new_dacl)) == 0
    try:
        create = kernel32.CreateFileW
        create.restype = _VP
        create.argtypes = [_WSTR, _U32, _U32, _VP, _U32, _U32, _VP]
        handle = _VP(
            create(
                str(path),
                _WRITE_DAC | _WRITE_OWNER | _READ_CONTROL,
                0x00000007,
                None,
                _OPEN_EXISTING,
                _BACKUP_SEMANTIC if is_dir else _NORMAL,
                None,
            )
        )
        assert handle.value not in (None, 0, _INVALID_HANDLE)
        try:
            setter = advapi.SetSecurityInfo  # advapi32 export for the SetSecurityInfoW macro
            setter.restype = _U32
            setter.argtypes = [_VP, _I32, _U32, _VP, _VP, _VP, _VP]
            code = setter(
                handle, SE_FILE_OBJECT, _DACL_SI | _PROTECTED_DACL_SI, None, None, new_dacl, None
            )
            assert code == 0, f"fixture_SetSecurityInfo_failed_{code}"
        finally:
            closer = kernel32.CloseHandle
            closer.restype = _BOOL
            closer.argtypes = [_VP]
            closer(handle)
    finally:
        _free(new_dacl)


def _set_null_dacl(path: Path, *, is_dir: bool) -> None:
    """NULL DACL: the kernel grants everyone full access. Must never verify."""
    advapi = _advapi()
    kernel32 = _kernel32()
    create = kernel32.CreateFileW
    create.restype = _VP
    create.argtypes = [_WSTR, _U32, _U32, _VP, _U32, _U32, _VP]
    handle = _VP(
        create(
            str(path),
            _WRITE_DAC | _READ_CONTROL,
            0x00000007,
            None,
            _OPEN_EXISTING,
            _BACKUP_SEMANTIC if is_dir else _NORMAL,
            None,
        )
    )
    assert handle.value not in (None, 0, _INVALID_HANDLE)
    try:
        setter = advapi.SetSecurityInfo
        setter.restype = _U32
        setter.argtypes = [_VP, _I32, _U32, _VP, _VP, _VP, _VP]
        assert setter(handle, SE_FILE_OBJECT, _DACL_SI, None, None, None, None) == 0
    finally:
        closer = kernel32.CloseHandle
        closer.restype = _BOOL
        closer.argtypes = [_VP]
        closer(handle)


def _startup_gate(path: Path) -> str:
    """How a caller must treat the two typed failures: any of them denies startup."""
    try:
        verify_owner_only(path)
    except (PrivatePathRejected, AclUnsupported):
        return "denied"
    return "granted"


@requires_windows
def test_apply_owner_only_passes_verification_for_file_and_dir(private_dir: Path) -> None:
    """(1) A file created under a private dir passes verification after apply_owner_only."""
    secret = private_dir / "account.refresh"
    secret.write_text(CANARY, encoding="utf-8")
    apply_owner_only(secret, is_dir=False)
    verify_owner_only(secret)
    apply_owner_only(private_dir, is_dir=True)
    verify_owner_only(private_dir)
    assert _startup_gate(secret) == "granted"


@requires_windows
def test_extra_everyone_ace_makes_verification_fail(private_dir: Path) -> None:
    """(2) A real second principal in the DACL is refused, by the real kernel readback."""
    secret = private_dir / "account.refresh"
    secret.write_text(CANARY, encoding="utf-8")
    apply_owner_only(secret, is_dir=False)
    everyone = _sid_of(EVERYONE)
    owner = _sid_of(current_user_sid_text())
    try:
        _write_dacl(secret, [(owner, 0), (everyone, 0)], is_dir=False)
    finally:
        _free(everyone, owner)
    with pytest.raises(PrivatePathRejected) as excinfo:
        verify_owner_only(secret)
    assert excinfo.value.safe_code.startswith("non_owner_allow_ace_")
    assert _startup_gate(secret) == "denied"


@requires_windows
def test_extra_builtin_users_ace_makes_verification_fail(private_dir: Path) -> None:
    secret = private_dir / "receipts.db"
    secret.write_bytes(b"x")
    apply_owner_only(secret, is_dir=False)
    users = _sid_of(BUILTIN_USERS)
    owner = _sid_of(current_user_sid_text())
    try:
        _write_dacl(secret, [(owner, 0), (users, 0)], is_dir=False)
    finally:
        _free(users, owner)
    with pytest.raises(PrivatePathRejected) as excinfo:
        verify_owner_only(secret)
    assert excinfo.value.safe_code == "non_owner_allow_ace_users"


@requires_windows
def test_dacl_that_grants_only_a_group_is_rejected(private_dir: Path) -> None:
    """A DACL with no owner ACE at all is not owner-only protection, whatever the mask."""
    secret = private_dir / "account.refresh"
    secret.write_text(CANARY, encoding="utf-8")
    apply_owner_only(secret, is_dir=False)
    everyone = _sid_of(EVERYONE)
    try:
        _write_dacl(secret, [(everyone, 0)], is_dir=False)
    finally:
        _free(everyone)
    with pytest.raises(PrivatePathRejected) as excinfo:
        verify_owner_only(secret)
    assert excinfo.value.safe_code == "non_owner_allow_ace_everyone"
    assert _startup_gate(secret) == "denied"


@requires_windows
def test_inherited_ace_makes_verification_fail(private_dir: Path) -> None:
    """(d) An inheritable grant on the private dir reaches child files: refused there too."""
    grantable = private_dir / "grant"
    grantable.mkdir()
    apply_owner_only(grantable, is_dir=True)
    everyone = _sid_of(EVERYONE)
    owner = _sid_of(current_user_sid_text())
    try:
        _write_dacl(
            grantable,
            [(owner, OBJECT_AND_CONTAINER_INHERIT), (everyone, OBJECT_AND_CONTAINER_INHERIT)],
            is_dir=True,
        )
    finally:
        _free(everyone, owner)
    child = grantable / "child.refresh"
    child.write_text(CANARY, encoding="utf-8")
    with pytest.raises(PrivatePathRejected) as excinfo:
        verify_owner_only(child)
    # Canonical order puts the owner's own ACE first, so inheritance is what fires here.
    assert excinfo.value.safe_code.startswith("ace_inherited_or_inheriting_")
    with pytest.raises(PrivatePathRejected) as parent:
        verify_owner_only(grantable)
    assert parent.value.safe_code.startswith("ace_inherited_or_inheriting_")
    assert _startup_gate(child) == "denied"


@requires_windows
def test_null_dacl_makes_verification_fail(private_dir: Path) -> None:
    """(3) A NULL DACL means everyone has full access: it is the loudest possible failure."""
    secret = private_dir / "account.refresh"
    secret.write_text(CANARY, encoding="utf-8")
    apply_owner_only(secret, is_dir=False)
    _set_null_dacl(secret, is_dir=False)
    with pytest.raises(PrivatePathRejected) as excinfo:
        verify_owner_only(secret)
    assert excinfo.value.safe_code == "null_dacl_grants_everyone"
    assert _startup_gate(secret) == "denied"


@requires_windows
def test_null_dacl_on_a_directory_makes_verification_fail(private_dir: Path) -> None:
    _set_null_dacl(private_dir, is_dir=True)
    with pytest.raises(PrivatePathRejected) as excinfo:
        verify_owner_only(private_dir)
    assert excinfo.value.safe_code == "null_dacl_grants_everyone"


@requires_windows
def test_missing_path_fails_closed(tmp_path: Path) -> None:
    """(4) A path that is not there is a denial, never a silent pass."""
    absent = tmp_path / "private" / "absent.refresh"
    assert not absent.exists()
    with pytest.raises(PrivatePathRejected) as excinfo:
        verify_owner_only(absent)
    assert excinfo.value.safe_code == "private_path_missing"
    assert _startup_gate(absent) == "denied"
    with pytest.raises(PrivatePathRejected):
        apply_owner_only(absent, is_dir=False)


def test_non_windows_platform_is_a_denial_not_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(5) AclUnsupported is raised off-Windows and the caller treats it as a denial."""
    target = tmp_path / "private"
    target.mkdir()
    monkeypatch.setattr(acl_mod, "IS_WINDOWS", False)
    with pytest.raises(AclUnsupported) as excinfo:
        verify_owner_only(target)
    assert excinfo.value.safe_code == "acl_unsupported_platform"
    assert _startup_gate(target) == "denied"
    with pytest.raises(AclUnsupported):
        apply_owner_only(target, is_dir=True)
    assert issubclass(AclUnsupported, ConnectorError)
    assert issubclass(PrivatePathRejected, ConnectorError)


@requires_windows
def test_rejection_text_carries_no_file_content(
    private_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """(6) Denials are safe to log: code plus at most a SID, never the protected bytes."""
    secret = private_dir / "account.refresh"
    secret.write_text(CANARY, encoding="utf-8")
    apply_owner_only(secret, is_dir=False)
    everyone = _sid_of(EVERYONE)
    owner = _sid_of(current_user_sid_text())
    try:
        _write_dacl(secret, [(owner, 0), (everyone, 0)], is_dir=False)
    finally:
        _free(everyone, owner)
    with caplog.at_level(logging.DEBUG), pytest.raises(PrivatePathRejected) as excinfo:
        try:
            verify_owner_only(secret)
        except PrivatePathRejected as rejection:
            logging.getLogger("probation.startup").error("acl denial: %s", rejection)
            raise
    message = str(excinfo.value)
    rendered = repr(excinfo.value)
    assert CANARY not in message
    assert CANARY not in rendered
    assert CANARY not in caplog.text
    assert secret.read_text(encoding="utf-8") == CANARY  # file bytes stayed in the file
    assert str(private_dir) not in message
    assert message == excinfo.value.safe_code
    assert len(message) < 120
    assert message.isascii()


@requires_windows
def test_protected_file_survives_a_write_verify_read_verify_round_trip(private_dir: Path) -> None:
    """(7) Readback keeps proving it: write, verify, read back, verify again."""
    secret = private_dir / "account.refresh"
    secret.write_text("opaque-refresh-state", encoding="utf-8")
    apply_owner_only(secret, is_dir=False)
    verify_owner_only(secret)
    assert secret.read_text(encoding="utf-8") == "opaque-refresh-state"
    verify_owner_only(secret)
    secret.write_text("rotated-refresh-state", encoding="utf-8")
    verify_owner_only(secret)
    assert secret.read_text(encoding="utf-8") == "rotated-refresh-state"


@requires_windows
def test_apply_owner_only_is_repeatable_and_still_minimal(private_dir: Path) -> None:
    """(8) Re-application is idempotent and the DACL stays exactly one owner-only allow ACE.

    ``verify_owner_only`` proves only "no non-owner access"; this test additionally proves the
    DACL has not accumulated duplicate ACEs across the two applications, reading the raw ACL
    back from the kernel rather than trusting the module's own verdict.
    """
    secret = private_dir / "account.refresh"
    secret.write_text("x", encoding="utf-8")
    apply_owner_only(secret, is_dir=False)
    apply_owner_only(secret, is_dir=False)
    verify_owner_only(secret)

    me = acl_mod._process_user_sid()
    descriptor, owner, dacl = acl_mod._read_security(secret)
    try:
        assert acl_mod._same_sid(owner, me.address)
        assert dacl is not None
        aces = acl_mod._enumerate_aces(dacl)
        assert len(aces) == 1
        ace_type, ace_flags, ace_sid = aces[0]
        assert ace_type == acl_mod._ACCESS_ALLOWED_ACE_TYPE
        assert ace_flags == 0
        assert acl_mod._same_sid(ace_sid, me.address)
    finally:
        acl_mod._apis().local_free(_VP(descriptor))


def test_acl_module_is_stdlib_only() -> None:
    source = Path(acl_mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("pip install", "subprocess", "win32security", "ntsecuritycon", "pywin32"):
        assert forbidden not in source
    assert "ctypes" in source
