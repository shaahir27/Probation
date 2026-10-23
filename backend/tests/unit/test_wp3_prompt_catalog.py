"""WP3 P02: the prompt catalog is complete, immutable and refuses to guess.

Requirement 7.2.1/7.2.2/7.2.3 are about the assets a request is built from, so every test here
attacks a way the loader could quietly send something nobody reviewed: an unregistered version,
an asset that disagrees with the registry, a manifest edited by hand, front matter that is only
*shaped* like metadata, or a template with a hole a sender could fill.
"""

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from probation.llm import prompt_loader
from probation.llm.catalog import JOBS, JobNotRegistered, ModelRole, resolve_job
from probation.llm.prompt_loader import (
    MANIFEST_NAME,
    PromptAsset,
    PromptAssetError,
    compile_request,
    load_prompt,
    manifest_hash,
    provider_schema,
    render,
    schema_fingerprint,
)
from probation.llm.results import FailureCode

MAIL = resolve_job("reader.mail", "v3")


@pytest.fixture(autouse=True)
def fresh_asset_caches():
    """Assets are cached for the life of a process; each test must see the disk it tampered with."""
    load_prompt.cache_clear()
    prompt_loader._manifest.cache_clear()
    yield
    load_prompt.cache_clear()
    prompt_loader._manifest.cache_clear()


def tamper(monkeypatch: pytest.MonkeyPatch, text: str, *, name: str | None = None) -> None:
    """Replace one asset's bytes with hostile text, leaving the real catalog untouched."""
    target = name or MAIL.asset
    original = prompt_loader._read_asset

    def read(asset_name: str) -> str:
        return text if asset_name == target else original(asset_name)

    monkeypatch.setattr(prompt_loader, "_read_asset", read)


def test_every_registered_job_resolves_to_its_own_verified_asset() -> None:
    """W3-T06: no job borrows a neighbour's prompt, and none of them falls back to a generic one."""
    loaded = {spec.qualified_id: load_prompt(spec) for spec in JOBS.values()}
    assert set(loaded) == {spec.qualified_id for spec in JOBS.values()}
    for spec in JOBS.values():
        asset = loaded[spec.qualified_id]
        assert asset.system.strip() and asset.user.strip()
        assert asset.spec.asset == spec.asset
        identity = asset.request_identity()
        assert identity["prompt_id"] == spec.prompt_id
        assert identity["prompt_version"] == spec.prompt_version
        assert identity["template_hash"] == asset.template_hash
        assert identity["schema_fingerprint"] == asset.schema_fingerprint


def test_a_superseded_version_is_not_a_job() -> None:
    """An old prompt id/version pair fails closed at the registry, before any asset is read."""
    with pytest.raises(JobNotRegistered):
        resolve_job("reader.mail", "v2")
    with pytest.raises(JobNotRegistered):
        resolve_job("reader.mail", "v99")


def test_a_missing_asset_is_a_typed_failure_not_an_empty_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Missing:
        def read_text(self, encoding: str = "utf-8") -> str:
            raise FileNotFoundError

    monkeypatch.setattr(
        prompt_loader, "files", lambda _package: SimpleNamespace(joinpath=lambda *_p: _Missing())
    )
    with pytest.raises(PromptAssetError) as raised:
        load_prompt(MAIL)
    assert raised.value.code is FailureCode.ASSET_MISSING


def test_front_matter_that_is_only_yaml_shaped_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W3-D01: metadata is JSON parsed by the standard library, so no YAML parser is implied."""
    yamlish = (
        "---\nid: reader.mail\nversion: v3\nmodel_role: reader\n---\n## system\nx\n## user\ny\n"
    )
    tamper(monkeypatch, yamlish)
    with pytest.raises(PromptAssetError) as raised:
        load_prompt(MAIL)
    assert "not valid JSON" in str(raised.value)
    assert "yaml" not in {name.lower() for name in vars(prompt_loader)}


def test_a_repeated_or_missing_section_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    tamper(monkeypatch, "---\n{}\n---\n## system\na\n## system\nb\n## user\nc\n")
    with pytest.raises(PromptAssetError) as repeated:
        load_prompt(MAIL)
    assert "repeats a section" in str(repeated.value)

    tamper(monkeypatch, "---\n{}\n---\n## system\na\n## semantic\nb\n")
    with pytest.raises(PromptAssetError) as missing:
        load_prompt(MAIL)
    assert "missing sections" in str(missing.value)


def test_an_asset_that_disagrees_with_the_registry_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The declared placeholder set, the role and the version are cross-checked, never trusted."""
    for drift in (
        replace(MAIL, prompt_version="v9"),
        replace(MAIL, model_role=ModelRole.WRITER),
        replace(MAIL, declares=("subject", "body")),
    ):
        with pytest.raises(PromptAssetError):
            load_prompt(drift)


def test_a_single_edited_word_in_an_asset_denies_the_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Immutability: the manifest digest is checked against the bytes that would be sent."""
    real = prompt_loader._read_asset(MAIL.asset)
    tamper(monkeypatch, real.replace("form-filling tool", "helpful assistant"))
    with pytest.raises(PromptAssetError) as raised:
        load_prompt(MAIL)
    assert "differ from the manifest hash" in str(raised.value)


def test_a_manifest_edited_to_match_a_different_schema_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A regenerated manifest cannot launder a schema change nobody reviewed."""
    real = json.loads(prompt_loader._read_asset(MANIFEST_NAME))
    real["assets"][MAIL.qualified_id]["schema_fingerprint"] = "0" * 16
    tamper(monkeypatch, json.dumps(real), name=MANIFEST_NAME)
    with pytest.raises(PromptAssetError) as raised:
        load_prompt(MAIL)
    assert "schema fingerprint drifted" in str(raised.value)


def test_an_asset_absent_from_the_manifest_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    real = json.loads(prompt_loader._read_asset(MANIFEST_NAME))
    del real["assets"][MAIL.qualified_id]
    tamper(monkeypatch, json.dumps(real), name=MANIFEST_NAME)
    with pytest.raises(PromptAssetError) as raised:
        load_prompt(MAIL)
    assert "absent from the prompt manifest" in str(raised.value)


def test_manifest_hash_is_the_committed_bytes_not_a_rebuild() -> None:
    text = prompt_loader._read_asset(MANIFEST_NAME)
    assert manifest_hash() == hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    assert manifest_hash() == manifest_hash()


def test_render_refuses_a_hole_it_was_not_given_values_for() -> None:
    with pytest.raises(PromptAssetError) as raised:
        render("Subject: {subject}\n{body}", {"subject": "hi"}, limit=200, label="reader.mail.v3")
    assert "needs values for" in str(raised.value)


def test_render_refuses_a_brace_expression_it_never_declared() -> None:
    """An undeclared brace cannot become a second injection point behind the context builder."""
    with pytest.raises(PromptAssetError) as raised:
        render("To: {Attention}\n{subject}", {"subject": "hi"}, limit=200, label="reader.mail.v3")
    assert "undeclared brace" in str(raised.value)


def test_render_does_not_expand_a_placeholder_shape_that_came_from_data() -> None:
    out = render("Body:\n{body}", {"body": "{subject} and {body}"}, limit=200, label="x")
    assert out == "Body:\n{subject} and {body}"


def test_render_reports_its_bound_as_a_typed_context_failure() -> None:
    with pytest.raises(PromptAssetError) as raised:
        render("{body}", {"body": "n" * 50}, limit=20, label="reader.mail.v3")
    assert raised.value.code is FailureCode.CONTEXT_TOO_LARGE


def test_compile_request_keeps_semantic_definition_with_the_system_role() -> None:
    asset = load_prompt(MAIL)
    assert isinstance(asset, PromptAsset)
    system, user = compile_request(
        asset,
        {"subject": "Zoom call", "sender_domain_class": "corp", "body": "hi"},
        user_limit=4000,
    )
    assert asset.semantic in system and system != asset.system
    assert "{subject}" not in user and "Zoom call" in user


def test_every_job_ships_a_closed_schema_generated_from_its_own_model() -> None:
    """I-1: the wire schema and the validating model are one object, never two hand-written ones."""
    for spec in JOBS.values():
        schema = provider_schema(spec)
        assert schema["additionalProperties"] is False
        assert json.dumps(schema)  # transport-safe before any request exists
        assert schema == spec.output_model().model_json_schema() | {"additionalProperties": False}


def test_a_job_with_no_registered_output_model_fails_before_http() -> None:
    """A registry entry that no model answers is a registry bug, and it denies rather than guesses."""
    assert MAIL.output_model() is not None
    with pytest.raises(JobNotRegistered):
        replace(MAIL, prompt_id="reader.noir").output_model()


def test_schema_fingerprint_is_stable_and_distinguishes_models() -> None:
    mail = schema_fingerprint(resolve_job("reader.mail", "v3").output_model())
    file_ = schema_fingerprint(resolve_job("reader.file", "v1").output_model())
    assert mail == schema_fingerprint(load_prompt(MAIL).spec.output_model())
    assert len(mail) == 16 and mail != file_
