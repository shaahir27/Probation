"""Gmail read connector: cohort-gated REST reads over an injected HttpTransport.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 1 and 4; docs/FULL_PRODUCT_SPEC.md 5.1/7.2.
Every call leaves through the injected transport (no ``if synthetic:`` branch). The cohort gate
runs before any body fetch, and the four Gmail identifiers — native message id, RFC Message-ID,
thread id, history id — stay separate and are never substituted by a provider field labelled
"updated".
"""

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from probation.connectors.types import (
    CapabilityManifest,
    CapabilityState,
    ConnectorError,
    HttpResult,
    HttpTransport,
    LabelTransition,
    LabelVersionEvidence,
    NativeRef,
    PayloadWriter,
    ProviderUnavailable,
    SelectionViolation,
    SourceObservation,
    SourceSelection,
    advance_versions,
)
from probation.core.clock import Clock
from probation.db.gmail_store import ConnectorAccess
from probation.packs.mail.connectors.gmail_mime import DEFAULT_LIMITS, MimeLimits, parse_message
from probation.packs.mail.connectors.gmail_payloads import payload_from_parsed
from probation.packs.mail.connectors.gmail_transport import quote_native_id

GMAIL_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
READ_ONLY_SCOPE = "gmail.readonly"


class GmailReadConnector:
    """Reads the approved cohort only. Never requests a body outside the proven selection."""

    def __init__(
        self,
        transport: HttpTransport,
        *,
        connection_id: str,
        account_id: str,
        access_token: str,
        clock: Clock,
        base_url: str = GMAIL_BASE_URL,
        owner_label: str | None = None,
        max_results: int = 100,
        mime_limits: MimeLimits = DEFAULT_LIMITS,
        payloads: PayloadWriter | None = None,
        token_provider: Callable[[], str] | None = None,
    ) -> None:
        if not access_token and token_provider is None:
            raise ConnectorError("access_token_unconfigured")
        self._token_provider = token_provider
        self._transport = transport
        self._connection_id = connection_id
        self._account_id = account_id
        self._access_token = access_token
        self._clock = clock
        self._base_url = base_url
        self._owner_label = owner_label
        self._max_results = max_results
        self._mime_limits = mime_limits
        self._payloads = payloads
        self._proven: set[str] = set()
        self._selection: SourceSelection | None = None
        self._resync_required = False

    def _auth(self) -> str:
        return self._access_token if self._token_provider is None else self._token_provider()

    # -- capability truth -------------------------------------------------------------------
    def capabilities(self) -> CapabilityManifest:
        """A truthful manifest: Gmail offers no conditional write (C1), history is windowed (C2)."""
        now = self._clock.now_iso()
        return CapabilityManifest(
            provider="gmail",
            provider_version="v1",
            granted_scopes=(READ_ONLY_SCOPE,),
            idempotency="none",
            reconciliation="bounded_local_evidence",
            states=(
                CapabilityState(
                    name="read",
                    supported=True,
                    verified_at=now,
                    evidence="supported",
                    reason="readonly_scope_enumeration_and_bounded_fetch",
                ),
                CapabilityState(
                    name="undo_history_proof",
                    supported=True,
                    verified_at=now,
                    evidence="supported",
                    reason="window_bounded_history_about_one_week",
                ),
                CapabilityState(
                    name="reconciliation",
                    supported=True,
                    verified_at=now,
                    evidence="supported",
                    reason="bounded_sent_search_not_exact_c8",
                ),
                CapabilityState(
                    name="conditional_write",
                    supported=False,
                    verified_at=now,
                    evidence="unsupported",
                    reason="modify_has_no_precondition_c1",
                ),
            ),
        )

    # -- transport helpers ------------------------------------------------------------------
    def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        result = self._transport.get(
            f"{self._base_url}{path}", params=params, access_token=self._auth()
        )
        return self._decode(result)

    @staticmethod
    def _decode(result: HttpResult) -> dict[str, Any]:
        if not result.ok:
            raise ProviderUnavailable(f"provider_status_{result.status}")
        try:
            payload = json.loads(result.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderUnavailable("malformed_provider_response") from exc
        if not isinstance(payload, Mapping):
            raise ProviderUnavailable("malformed_provider_response")
        return dict(payload)

    # -- bootstrap anchor -------------------------------------------------------------------
    def bootstrap_anchor(self) -> int:
        """Capture the account ``historyId`` before paginating, to bound the catch-up interval."""
        profile = self._request("/profile", {})
        raw = profile.get("historyId")
        if not isinstance(raw, (str, int)) or not str(raw).isdigit():
            raise ProviderUnavailable("missing_profile_history_id")
        return int(str(raw))

    def history_page(self, params: dict[str, object]) -> dict[str, object]:
        """One bounded ``users.history.list`` call. A stale/out-of-range ``startHistoryId`` answers
        HTTP 404 (C3): this flags a resync and still raises ``provider_status_404``
        (``ProviderUnavailable``) so the sync layer forces an explicit re-sync, never an empty poll."""
        request_params: dict[str, Any] = dict(params)
        result = self._transport.get(
            f"{self._base_url}/history",
            params=request_params,
            access_token=self._auth(),
        )
        if result.status == 404:
            self._resync_required = True
        return self._decode(result)

    # -- cohort enumeration (ids only, never bodies) ----------------------------------------
    def enumerate_cohort(self, selection: SourceSelection) -> tuple[NativeRef, ...]:
        """Prove cohort membership by bounded ``messages.list``; store nothing but the refs.

        An owner-label cohort enumerates by that label, so a selected message stays tracked after
        ``INBOX`` removal: the label, not the inbox, defines the cohort.
        """
        self._reject_foreign_selection(selection)
        self._selection = selection
        self._proven = set()
        explicit = set(selection.native_message_ids)
        refs: list[NativeRef] = []
        if self._owner_label is not None or selection.label_ids:
            for label_id in selection.label_ids or (
                (self._owner_label,) if self._owner_label else ()
            ):
                refs.extend(self._enumerate_by_label(selection, label_id, explicit))
        elif explicit:
            for native_id in sorted(explicit):
                refs.append(
                    NativeRef(
                        connection_id=selection.connection_id,
                        account_id=selection.account_id,
                        native_message_id=native_id,
                    )
                )
                self._proven.add(native_id)
        return tuple(refs)

    def _enumerate_by_label(
        self, selection: SourceSelection, label_id: str, explicit: set[str]
    ) -> list[NativeRef]:
        collected: list[NativeRef] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"labelId": label_id, "maxResults": self._max_results}
            if page_token is not None:
                params["pageToken"] = page_token
            payload = self._request("/messages", params)
            for item in payload.get("messages", []):
                if not isinstance(item, Mapping):
                    continue
                native_id = str(item.get("id", ""))
                if not native_id:
                    continue
                if explicit and native_id not in explicit:
                    continue
                self._proven.add(native_id)
                thread = item.get("threadId")
                collected.append(
                    NativeRef(
                        connection_id=selection.connection_id,
                        account_id=selection.account_id,
                        native_message_id=native_id,
                        thread_id=str(thread) if thread else None,
                    )
                )
            page_token = payload.get("nextPageToken")
            if page_token is None:
                return collected

    # -- cohort-gated body fetch ------------------------------------------------------------
    def prove(self, native_ids: set[str]) -> None:
        """Add resources just proven cohort by an owner-label event, so a body may be fetched."""
        self._proven.update(native_ids)

    def proven(self) -> frozenset[str]:
        return frozenset(self._proven)

    def observe(
        self,
        ref: NativeRef,
        *,
        observed_at: str | None = None,
        payloads: PayloadWriter | None = None,
    ) -> SourceObservation:
        """Fetch and normalize a body for a resource already proven inside the cohort.

        A resource never enumerated raises ``SelectionViolation`` before any ``messages.get``, so
        an out-of-cohort id triggers zero body calls. ``observed_at`` is the local knowledge time
        from the injected Clock unless the caller supplies one; never the provider ``Date`` header.
        The parsed content is persisted through the payload writer before an observation exists:
        a failed write raises and the caller emits no row (fail closed).
        """
        if ref.native_message_id not in self._proven:
            raise SelectionViolation("cohort_required_before_body")
        self._reject_foreign_ref(ref)
        writer = payloads if payloads is not None else self._payloads
        if writer is None:
            raise ConnectorError("payload_store_unconfigured")
        payload = self._request(
            f"/messages/{quote_native_id(ref.native_message_id)}",
            {"format": "full", "includeHeaders": "true"},
        )
        parsed = parse_message(payload, limits=self._mime_limits)
        record = payload_from_parsed(parsed)
        payload_ref = writer.write(record)
        return self._to_observation(
            parsed, observed_at or self._clock.now_iso(), payload_ref, record.content_hash
        )

    def fetch_message(
        self, ref: NativeRef, *, payloads: PayloadWriter | None = None
    ) -> SourceObservation:
        """Alias for observe, satisfying live test contracts."""
        return self.observe(ref, payloads=payloads)

    def _to_observation(
        self, parsed: Any, observed_at: str, payload_ref: str, content_hash: str
    ) -> SourceObservation:
        event_type = "sent_observed" if parsed.is_sent else "message_added"
        version_hash = _sha(
            _canonical(
                {
                    "connection_id": self._connection_id,
                    "native_message_id": parsed.native_message_id,
                    "thread_id": parsed.thread_id,
                    "labels": sorted(parsed.label_ids),
                    "message_history_id": parsed.history_id,
                }
            )
        )
        return SourceObservation(
            connection_id=self._connection_id,
            account_id=self._account_id,
            native_message_id=parsed.native_message_id,
            history_id=parsed.history_id,
            event_type=event_type,  # type: ignore[arg-type]
            content_hash=content_hash,
            version_hash=version_hash,
            observed_at=observed_at,
            provenance="provider_occurrence",
            payload_ref=payload_ref,
            thread_id=parsed.thread_id,
            occurrence_time=parsed.occurrence_time,
            label_ids=parsed.label_ids,
            rfc_message_id=parsed.rfc_message_id,
            is_selected=True,
        )

    # -- selection / ref guards -------------------------------------------------------------
    def _reject_foreign_selection(self, selection: SourceSelection) -> None:
        if (
            selection.connection_id != self._connection_id
            or selection.account_id != self._account_id
        ):
            raise SelectionViolation("selection_account_mismatch")

    def _reject_foreign_ref(self, ref: NativeRef) -> None:
        if not ref.connection_id == self._connection_id or ref.account_id != self._account_id:
            raise SelectionViolation("ref_account_mismatch")
        selection = self._selection
        if selection is not None and not selection.covers(ref):
            raise SelectionViolation("ref_outside_selection")

    # -- cohort history projection and label versions ---------------------------------------
    def cohort_transitions(
        self, history: Sequence[Mapping[str, Any]]
    ) -> tuple[LabelTransition, ...]:
        """Project provider history to in-cohort label transitions; out-of-cohort yields nothing.

        No transition, id or label name for a message outside the cohort. The owner label defines
        membership, so a late-labelled message joins and tracking survives ``INBOX`` removal.
        """
        transitions: list[LabelTransition] = []
        for entry in history:
            if not isinstance(entry, Mapping):
                continue
            history_id = _as_int(entry.get("id"))
            if history_id is None:
                continue
            for key, added in (("labelAdded", True), ("labelRemoved", False)):
                for record in _records_of(entry, key):
                    label_id = record.get("labelId")
                    if not isinstance(label_id, str) or not label_id:
                        continue
                    is_owner = self._owner_label is not None and label_id == self._owner_label
                    for native_id in _record_message_ids(record):
                        if is_owner and added:
                            self._proven.add(native_id)
                        if native_id not in self._proven:
                            continue
                        transitions.append(
                            LabelTransition(
                                native_message_id=native_id,
                                label_id=label_id,
                                history_id=history_id,
                                added=added,
                            )
                        )
        return tuple(transitions)

    def label_version_evidence(
        self,
        native_message_id: str,
        *,
        access: ConnectorAccess,
        anchor_history_id: int | None = None,
        baseline: dict[str, int] | None = None,
        window_complete: bool = True,
        retained_from: int | None = None,
        resync_required: bool = False,
    ) -> LabelVersionEvidence:
        """Derive per-label versions ONLY from persisted ``gmail_history_events`` rows via
        ``advance_versions``; never synthesize, pad or default a count. ``continuous`` is false
        without an anchor, after a resync, on a gap, or when the anchor predates retained history.
        """
        rows = access.query(
            "SELECT label_id,event_type,history_id FROM gmail_history_events"
            " WHERE connection_id=? AND native_message_id=?"
            " AND event_type IN('labelAdded','labelRemoved') ORDER BY history_id",
            (self._connection_id, native_message_id),
        )
        transitions: list[LabelTransition] = []
        for row in rows:
            history_id = _as_int(row["history_id"])
            if history_id is None:
                continue
            if anchor_history_id is not None and history_id <= anchor_history_id:
                continue
            transitions.append(
                LabelTransition(
                    native_message_id=native_message_id,
                    label_id=str(row["label_id"]),
                    history_id=history_id,
                    added=str(row["event_type"]) == "labelAdded",
                )
            )
        versions = advance_versions(dict(baseline or {}), tuple(transitions), native_message_id)
        continuous = bool(
            window_complete
            and anchor_history_id is not None
            and not (resync_required or self._resync_required)
            and not (retained_from is not None and anchor_history_id < retained_from)
        )
        return LabelVersionEvidence(
            native_message_id=native_message_id,
            versions=versions,
            continuous=continuous,
            anchor_history_id=anchor_history_id,
        )


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _records_of(entry: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    raw = entry.get(key)
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return [item for item in raw if isinstance(item, Mapping)]
    return []


def _record_message_ids(record: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    messages = record.get("messages")
    if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes)):
        for message in messages:
            if isinstance(message, Mapping) and isinstance(message.get("id"), str):
                ids.append(str(message["id"]))
    return ids
