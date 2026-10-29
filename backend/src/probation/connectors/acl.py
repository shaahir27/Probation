"""Owner-only Windows ACL enforcement for D4 private state. Standard library only.

Authority: ``docs/WP12_D4_GMAIL_CONTRACT.md`` section 5 — persisted refresh state and native
receipts live under gitignored ``data/private/`` behind *verified* owner-only Windows ACLs and
a failed ACL check denies startup — and ``docs/SECURITY_PRIVACY.md`` (class B: personal data,
local only). No third-party ACL package is permitted, so everything below is ``ctypes`` against
``advapi32``/``kernel32``.

The guarantee is read back from the kernel, never assumed. A path is owner-only only when all
of these hold: (a) the descriptor owner is the current process user, (b) the DACL exists — a
NULL DACL grants everyone full access, (c) every ACE is an ``ACCESS_ALLOWED_ACE`` for that same
SID, and (d) no ACE is inherited or carrying inheritance flags. Every other case raises:
``AclUnsupported`` when the platform or API is unavailable, ``PrivatePathRejected`` when the
path is not protected. Neither is ever a pass — the module fails closed.

Rejection text carries a short code and, at most, a SID string: never the path's contents,
never a token, never a message body.
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from probation.connectors.types import ConnectorError

IS_WINDOWS: Final = os.name == "nt"

_P: Final = ctypes.c_void_p  # PSID, PACL, HANDLE and PSECURITY_DESCRIPTOR are opaque here.
_PP: Final = ctypes.POINTER(_P)
_U32: Final = ctypes.c_ulong
_I32: Final = ctypes.c_int
_BOOL: Final = ctypes.c_int
_WSTR: Final = ctypes.c_wchar_p

SE_FILE_OBJECT: Final = 1
_OWNER_SI: Final = 0x00000001
_GROUP_SI: Final = 0x00000002
_DACL_SI: Final = 0x00000004
_SACL_SI: Final = 0x00000008
_PROTECTED_DACL_SI: Final = 0x80000000
_READ_ALL: Final = _OWNER_SI | _GROUP_SI | _DACL_SI | _SACL_SI
_READ_WITHOUT_SACL: Final = _OWNER_SI | _GROUP_SI | _DACL_SI
_ACCESS_ALLOWED_ACE_TYPE: Final = 0
_ACL_SIZE_INFORMATION: Final = 2
_ACE_SID_OFFSET: Final = 8
_SET_ACCESS: Final = 2
_TRUSTEE_IS_SID: Final = 0
_TRUSTEE_IS_UNKNOWN: Final = 0
_FILE_ALL_ACCESS: Final = 0x1F01FF
_WRITE_DAC: Final = 0x00040000
_WRITE_OWNER: Final = 0x00080000
_READ_CONTROL: Final = 0x00020000
_FILE_SHARE_ALL: Final = 0x00000007
_OPEN_EXISTING: Final = 3
_FILE_ATTRIBUTE_NORMAL: Final = 0x00000080
_FILE_FLAG_BACKUP_SEMANTIC: Final = 0x02000000
_TOKEN_QUERY: Final = 0x0008
_TOKEN_USER: Final = 1
_INVALID_HANDLE: Final = 0xFFFFFFFFFFFFFFFF
_ERROR_FILE_NOT_FOUND: Final = 2
_ERROR_PATH_NOT_FOUND: Final = 3
_ERROR_ACCESS_DENIED: Final = 5
_ERROR_PRIVILEGE_NOT_HELD: Final = 1314
_SACL_DENIED_ERRORS: Final = (_ERROR_PRIVILEGE_NOT_HELD, _ERROR_ACCESS_DENIED)
_MISSING_PATH_ERRORS: Final = (_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND)
_WELL_KNOWN: Final = {
    "S-1-1-0": "everyone",
    "S-1-5-1": "authenticated-users",
    "S-1-5-2": "interactive",
    "S-1-5-11": "authenticated-users",
    "S-1-5-32-544": "administrators",
    "S-1-5-32-545": "users",
}


class PrivatePathRejected(ConnectorError):
    """The path is not provably owner-only. Callers must deny startup, never proceed."""


class AclUnsupported(ConnectorError):
    """The platform or the security API is unavailable. Also a denial: fail closed."""


class _TrusteeW(ctypes.Structure):
    _fields_ = [
        ("pMultipleTrustee", _PP),
        ("MultipleTrusteeOperation", _U32),
        ("TrusteeType", _U32),
        ("TrusteeForm", _U32),
        ("Name", _P),
    ]


class _ExplicitAccessW(ctypes.Structure):
    _fields_ = [
        ("grfAccessPermissions", _U32),
        ("grfAccessMode", _U32),
        ("grfInheritance", _U32),
        ("Trustee", _TrusteeW),
    ]


class _AclSizeInformation(ctypes.Structure):
    _fields_ = [("AceCount", _U32), ("AclBytesInUse", _U32), ("AclBytesFree", _U32)]


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", _P), ("Attributes", _U32)]


def _bind(fn: Any, restype: Any, argtypes: list[Any]) -> Any:
    fn.restype = restype
    fn.argtypes = argtypes
    return fn


def _export(lib: ctypes.WinDLL, names: tuple[str, ...]) -> Any:
    """Resolve the first exported name. ``SetSecurityInfoW`` is a header macro; advapi32
    exports ``SetSecurityInfo`` (verified on this host), so both spellings are tried."""
    for name in names:
        try:
            return getattr(lib, name)
        except AttributeError:
            continue
    raise AttributeError(f"missing export {names[0]}")


@dataclass(frozen=True)
class _Apis:
    get_current_process: Any
    open_process_token: Any
    get_token_information: Any
    get_length_sid: Any
    sid_to_text: Any
    get_named_security_info: Any
    set_security_info: Any
    set_entries_in_acl: Any
    get_acl_information: Any
    get_ace: Any
    equal_sid: Any
    create_file: Any
    close_handle: Any
    local_free: Any


_APIS: _Apis | None = None


def _apis() -> _Apis:
    """Bound API table, or a typed denial. Never a silent pass on a non-Windows host."""
    global _APIS
    if not IS_WINDOWS:
        raise AclUnsupported("acl_unsupported_platform")
    if _APIS is None:
        try:
            advapi = ctypes.WinDLL("advapi32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            _APIS = _Apis(
                get_current_process=_bind(kernel32.GetCurrentProcess, _P, []),
                open_process_token=_bind(advapi.OpenProcessToken, _BOOL, [_P, _U32, _PP]),
                get_token_information=_bind(
                    advapi.GetTokenInformation, _BOOL, [_P, _I32, _P, _U32, ctypes.POINTER(_U32)]
                ),
                get_length_sid=_bind(advapi.GetLengthSid, _U32, [_P]),
                sid_to_text=_bind(advapi.ConvertSidToStringSidW, _BOOL, [_P, _PP]),
                get_named_security_info=_bind(
                    advapi.GetNamedSecurityInfoW, _U32, [_WSTR, _I32, _U32, _PP, _PP, _PP, _PP, _PP]
                ),
                set_security_info=_bind(
                    _export(advapi, ("SetSecurityInfoW", "SetSecurityInfo")),
                    _U32,
                    [_P, _I32, _U32, _P, _P, _P, _P],
                ),
                set_entries_in_acl=_bind(advapi.SetEntriesInAclW, _U32, [_U32, _P, _P, _PP]),
                get_acl_information=_bind(advapi.GetAclInformation, _BOOL, [_P, _P, _U32, _I32]),
                get_ace=_bind(advapi.GetAce, _BOOL, [_P, _U32, _PP]),
                equal_sid=_bind(advapi.EqualSid, _BOOL, [_P, _P]),
                create_file=_bind(
                    kernel32.CreateFileW, _P, [_WSTR, _U32, _U32, _P, _U32, _U32, _P]
                ),
                close_handle=_bind(kernel32.CloseHandle, _BOOL, [_P]),
                local_free=_bind(kernel32.LocalFree, _P, [_P]),
            )
        except (AttributeError, OSError) as exc:
            raise AclUnsupported("acl_api_unavailable") from exc
    return _APIS


@dataclass(frozen=True)
class _UserSid:
    text: str
    address: int
    _keepalive: ctypes.Array[ctypes.c_char]

    @property
    def pointer(self) -> ctypes.c_void_p:
        return _P(self.address)


def _sid_text(address: int) -> str:
    api = _apis()
    text = _P()
    if not api.sid_to_text(_P(address), ctypes.byref(text)) or not text.value:
        return "sid-unreadable"
    try:
        return str(ctypes.wstring_at(int(text.value)))
    finally:
        api.local_free(text)


def _sid_label(address: int) -> str:
    """Safe principal text for an error code: a well-known label or the SID string only."""
    text = _sid_text(address)
    return _WELL_KNOWN.get(text, text)


def _process_user_sid() -> _UserSid:
    api = _apis()
    token = _P()
    if not api.open_process_token(api.get_current_process(), _TOKEN_QUERY, ctypes.byref(token)):
        raise AclUnsupported("process_token_unavailable")
    try:
        needed = _U32()
        api.get_token_information(token, _TOKEN_USER, None, 0, ctypes.byref(needed))
        buffer = ctypes.create_string_buffer(needed.value)
        if not api.get_token_information(token, _TOKEN_USER, buffer, needed, ctypes.byref(needed)):
            raise AclUnsupported("token_user_sid_unavailable")
        entry = _SidAndAttributes.from_buffer_copy(buffer.raw[: ctypes.sizeof(_SidAndAttributes)])
        sid_address = int(entry.Sid or 0)
        if not sid_address:
            raise AclUnsupported("token_user_sid_empty")
        length = api.get_length_sid(_P(sid_address))
        owned = ctypes.create_string_buffer(int(length))
        ctypes.memmove(owned, _P(sid_address), int(length))
        address = ctypes.addressof(owned)
        text = _sid_text(address)
        if not text.startswith("S-"):
            raise AclUnsupported("sid_conversion_unavailable")
        return _UserSid(text=text, address=address, _keepalive=owned)
    finally:
        api.close_handle(token)


def current_user_sid_text() -> str:
    """The current process user's SID string. Safe to log; it is an identifier, not content."""
    return _process_user_sid().text


def _same_sid(address: int, other: int) -> bool:
    return bool(_apis().equal_sid(_P(address), _P(other)))


def _open_handle(path: Path, is_dir: bool, access: int) -> int:
    api = _apis()
    flags = _FILE_FLAG_BACKUP_SEMANTIC if is_dir else _FILE_ATTRIBUTE_NORMAL
    handle = api.create_file(str(path), access, _FILE_SHARE_ALL, None, _OPEN_EXISTING, flags, None)
    if handle in (None, 0, _INVALID_HANDLE):
        raise PrivatePathRejected(f"path_handle_denied_{ctypes.get_last_error()}")
    return int(handle)


def _read_security(path: Path) -> tuple[int, int, int | None]:
    """Return (descriptor, owner SID, DACL or None). The caller owns LocalFree on the descriptor.

    Reading a SACL needs SeSecurityPrivilege, which an ordinary user process does not hold.
    The second pass drops it from what is *read*, never from what is judged: checks (a)-(d)
    do not consult the SACL, so the verdict is unchanged and still comes from the kernel.
    """
    api = _apis()
    code = 0
    owner, dacl, descriptor = _P(), _P(), _P()
    for flags in (_READ_ALL, _READ_WITHOUT_SACL):
        group, sacl = _P(), _P()
        owner, dacl, descriptor = _P(), _P(), _P()
        code = api.get_named_security_info(
            str(path),
            SE_FILE_OBJECT,
            flags,
            ctypes.byref(owner),
            ctypes.byref(group),
            ctypes.byref(dacl),
            ctypes.byref(sacl),
            ctypes.byref(descriptor),
        )
        if not code or code not in _SACL_DENIED_ERRORS:
            break
    if code:
        if code in _MISSING_PATH_ERRORS:
            raise PrivatePathRejected("private_path_missing")
        raise PrivatePathRejected(f"security_info_unreadable_{code}")
    if not descriptor.value or not owner.value:
        raise PrivatePathRejected("security_descriptor_incomplete")
    return int(descriptor.value), int(owner.value), int(dacl.value or 0) or None


def _enumerate_aces(dacl: int) -> list[tuple[int, int, int]]:
    """(type, flags, sid address) for every ACE, via GetAclInformation + GetAce."""
    api = _apis()
    info = _AclSizeInformation()
    if not api.get_acl_information(
        _P(dacl), ctypes.byref(info), ctypes.sizeof(info), _ACL_SIZE_INFORMATION
    ):
        raise PrivatePathRejected("acl_size_information_failed")
    aces: list[tuple[int, int, int]] = []
    for index in range(int(info.AceCount)):
        ace = _P()
        if not api.get_ace(_P(dacl), _U32(index), ctypes.byref(ace)) or not ace.value:
            raise PrivatePathRejected("ace_read_failed")
        address = int(ace.value)
        header = ctypes.cast(address, ctypes.POINTER(ctypes.c_ubyte * _ACE_SID_OFFSET))
        aces.append((int(header.contents[0]), int(header.contents[1]), address + _ACE_SID_OFFSET))
    return aces


def _owned_by_current_user(path: Path) -> bool:
    """Whether the descriptor owner already matches this process, without changing anything."""
    descriptor, owner, _ = _read_security(path)
    try:
        me = _process_user_sid()  # keep the SID buffer alive through EqualSid
        return _same_sid(owner, me.address)
    finally:
        _apis().local_free(_P(descriptor))


def apply_owner_only(path: Path, *, is_dir: bool) -> None:
    """Make ``path`` owner-only: the current user owns it and the DACL is one explicit ACE.

    The single ACE is built with ``EXPLICIT_ACCESS_W`` + ``SetEntriesInAclW`` (no old ACL is
    merged in) and written with ``SetSecurityInfo`` under ``PROTECTED_DACL_SECURITY_INFORMATION``
    so every inherited ACE is dropped. Inheritance flags are zero, so nothing propagates down.
    When the path is already owned by the current user, only the DACL is replaced; asking for
    ``WRITE_OWNER`` unnecessarily can be denied by a restricted token even though the owner can
    still protect its own path. The result is read back: this function never reports success
    without proof.
    """
    api = _apis()
    me = _process_user_sid()
    owned = _owned_by_current_user(path)
    request = _ExplicitAccessW()
    request.grfAccessPermissions = _FILE_ALL_ACCESS
    request.grfAccessMode = _SET_ACCESS
    request.grfInheritance = 0
    request.Trustee.TrusteeType = _TRUSTEE_IS_UNKNOWN
    request.Trustee.TrusteeForm = _TRUSTEE_IS_SID
    request.Trustee.Name = _P(me.address)
    new_dacl = _P()
    code = api.set_entries_in_acl(1, ctypes.byref(request), None, ctypes.byref(new_dacl))
    if code or not new_dacl.value:
        raise PrivatePathRejected(f"owner_only_dacl_build_failed_{code}")
    try:
        access = _WRITE_DAC | _READ_CONTROL | (0 if owned else _WRITE_OWNER)
        handle = _open_handle(path, is_dir, access)
        try:
            written = api.set_security_info(
                _P(handle),
                SE_FILE_OBJECT,
                _DACL_SI | _PROTECTED_DACL_SI | (0 if owned else _OWNER_SI),
                None if owned else me.pointer,
                None,
                new_dacl,
                None,
            )
        finally:
            api.close_handle(handle)
    finally:
        api.local_free(new_dacl)
    if written:
        raise PrivatePathRejected(f"owner_only_apply_failed_{written}")
    verify_owner_only(path)


def verify_owner_only(path: Path) -> None:
    """Deny unless ``path`` is provably owner-only. Raises; returns None only on proof."""
    me = _process_user_sid()
    if not path.exists():
        raise PrivatePathRejected("private_path_missing")
    descriptor, owner, dacl = _read_security(path)
    try:
        if not _same_sid(owner, me.address):
            raise PrivatePathRejected(f"owner_not_current_user_{_sid_label(owner)}")
        if dacl is None:
            raise PrivatePathRejected("null_dacl_grants_everyone")
        aces = _enumerate_aces(dacl)
        if not aces:
            raise PrivatePathRejected("empty_dacl_owner_has_no_access")
        for ace_type, ace_flags, ace_sid in aces:
            if ace_type != _ACCESS_ALLOWED_ACE_TYPE:
                raise PrivatePathRejected(f"unexpected_ace_type_{ace_type}")
            if ace_flags:
                raise PrivatePathRejected(f"ace_inherited_or_inheriting_{ace_flags:#04x}")
            if not _same_sid(ace_sid, me.address):
                raise PrivatePathRejected(f"non_owner_allow_ace_{_sid_label(ace_sid)}")
    finally:
        _apis().local_free(_P(descriptor))
