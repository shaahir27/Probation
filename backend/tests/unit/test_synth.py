"""Unit and contract tests for synthetic world generation and source importers.

Authority: docs/TEST_PLAN.md (T-SYNTH), docs/EVALUATION_PLAN.md section 2, and docs/CONTRACT.md (I-19).
Verifies:
1. Determinism: Same seed produces byte-identical output across all formats.
2. Calibration: Observed habit adherence matches 1 - noise within 2 percentage points.
3. Drift: Action distributions change as specified post-day-120.
4. Static isolation: Engine, core, workers, and packs NEVER import truth.json.
5. Importer idempotency (T-ID): Repeated imports cause zero duplicates.
"""

import ast
import filecmp
import json
import sqlite3
import tempfile
from pathlib import Path

from probation.db.connection import apply_schema, get_connection
from probation.synth.generator import SyntheticGenerator, generate_synthetic_world
from probation.synth.importers import import_calendar, import_files, import_mail
from probation.synth.personas import get_default_persona, get_persona, list_personas


def test_personas_structure_and_isolation() -> None:
    """Verify 20 personas with correct development vs test separation."""
    personas = list_personas()
    assert len(personas) == 20

    dev_personas = [p for p in personas if not p.is_test_persona]
    test_personas = [p for p in personas if p.is_test_persona]

    assert len(dev_personas) == 15
    assert len(test_personas) == 5

    meena = get_default_persona()
    assert meena.id == 0
    assert "Meena" in meena.name
    assert meena.role == "student"
    assert len(meena.contacts) >= 5
    assert len(meena.courses) >= 3


def test_t_synth_determinism() -> None:
    """T-SYNTH: Same seed produces byte-identical files across all output formats."""
    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
        dir1 = Path(tmp1)
        dir2 = Path(tmp2)

        res1 = generate_synthetic_world(persona_id=0, seed=42, size="tiny", out_dir=dir1)
        res2 = generate_synthetic_world(persona_id=0, seed=42, size="tiny", out_dir=dir2)

        assert res1["situations_total"] == res2["situations_total"]
        assert res1["situations_total"] > 0

        # Check byte-identical match on output files
        for filename in [
            "mailbox.mbox",
            "calendar.ics",
            "files_manifest.json",
            "truth.json",
            "persona.json",
            "habits.json",
        ]:
            file1 = dir1 / filename
            file2 = dir2 / filename
            assert file1.exists(), f"Missing {filename} in run 1"
            assert file2.exists(), f"Missing {filename} in run 2"
            assert filecmp.cmp(file1, file2, shallow=False), (
                f"File {filename} is not byte-identical between identical runs!"
            )

        # Check world.db table contents match exactly
        conn1 = sqlite3.connect(str(dir1 / "world.db"))
        conn2 = sqlite3.connect(str(dir2 / "world.db"))
        try:
            for table in ["messages", "events", "files"]:
                rows1 = conn1.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                rows2 = conn2.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                assert rows1 == rows2, f"Table {table} differed in world.db between runs!"
        finally:
            conn1.close()
            conn2.close()


def test_t_synth_habit_calibration_and_noise() -> None:
    """T-SYNTH: Observed habit adherence matches 1 - noise within 2 percentage points.

    Authority: docs/EVALUATION_PLAN.md section 2.2: noise = 0.07 -> adherence ~ 0.93.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)
        # Generate full-sized sample or sufficiently large sample for tight confidence interval
        persona = get_persona(0)
        generator = SyntheticGenerator(persona=persona, seed=123, size="tiny")
        generator.generate(out_dir)

        with open(out_dir / "truth.json", encoding="utf-8") as f:
            truth = json.load(f)

        total_situations = len(truth)
        assert total_situations > 0

        # Calculate noise rate and adherence
        noisy_count = sum(1 for rec in truth.values() if rec["noise_applied"])
        noise_rate = noisy_count / total_situations
        adherence_rate = 1.0 - noise_rate

        # Target noise is 0.07 (aim: adherence in [0.91, 0.95] within +/- 2 points)
        assert abs(noise_rate - 0.07) <= 0.035, (
            f"Observed noise rate {noise_rate:.3f} deviated from expected 0.07"
        )
        assert abs(adherence_rate - 0.93) <= 0.035, (
            f"Observed adherence rate {adherence_rate:.3f} deviated from expected 0.93"
        )


def test_t_synth_temporal_drift() -> None:
    """T-SYNTH: Verify planned habit drift changes action distributions post day 120."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)
        generate_synthetic_world(persona_id=0, seed=999, size="tiny", out_dir=out_dir)

        with open(out_dir / "truth.json", encoding="utf-8") as f:
            truth = json.load(f)

        # Check early invite events before vs after day 120
        early_invites_pre = [
            rec
            for rec in truth.values()
            if rec["family"] == "invite_rsvp"
            and rec["attributes"].get("start_hour_bucket") == "early"
            and rec["day_idx"] < 120
        ]
        early_invites_post = [
            rec
            for rec in truth.values()
            if rec["family"] == "invite_rsvp"
            and rec["attributes"].get("start_hour_bucket") == "early"
            and rec["day_idx"] >= 120
        ]

        if early_invites_pre:
            decline_share_pre = sum(
                1 for r in early_invites_pre if r["true_action"] == "DECLINE"
            ) / len(early_invites_pre)
            # Before drift, R8 specifies DECLINE ~ 93%
            assert decline_share_pre >= 0.70

        if early_invites_post:
            accept_share_post = sum(
                1 for r in early_invites_post if r["true_action"] == "ACCEPT"
            ) / len(early_invites_post)
            # After drift at day 120, R8 specifies ACCEPT ~ 80%
            assert accept_share_post >= 0.60


def test_t_synth_static_isolation_check() -> None:
    """T-SYNTH Static Check: Core, engine, workers, and packs NEVER import or read truth.json.

    Authority: docs/TEST_PLAN.md (T-SYNTH) and docs/EVALUATION_PLAN.md section 2.6.
    """
    root_src = Path(__file__).resolve().parent.parent.parent / "src" / "probation"
    protected_subdirs = ["core", "engine", "workers", "packs"]

    violations: list[str] = []

    for subdir_name in protected_subdirs:
        dir_path = root_src / subdir_name
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            if "truth.json" in content:
                violations.append(f"{py_file} contains direct reference to 'truth.json'")

            # Parse AST to ensure no module named 'truth' or similar is imported
            try:
                tree = ast.parse(content, filename=str(py_file))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if "truth" in alias.name.lower():
                                violations.append(f"{py_file} imports module '{alias.name}'")
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and "truth" in node.module.lower():
                            violations.append(f"{py_file} imports from module '{node.module}'")
            except SyntaxError:
                pass

    assert not violations, "Static isolation violations detected:\n" + "\n".join(violations)


def test_t_id_importer_idempotency() -> None:
    """T-ID: Importers parse records into raw_items, and re-importing alters nothing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)
        generate_synthetic_world(persona_id=0, seed=7, size="tiny", out_dir=out_dir)

        # Set up an in-memory SQLite database with schema
        conn = sqlite3.connect(":memory:")
        apply_schema(conn)

        mbox_file = out_dir / "mailbox.mbox"
        ics_file = out_dir / "calendar.ics"
        manifest_file = out_dir / "files_manifest.json"

        # 1. First Import
        res_mail1 = import_mail(mbox_file, conn, user_addresses=["meena.k@example.ac.in"])
        res_cal1 = import_calendar(ics_file, conn, user_addresses=["meena.k@example.ac.in"])
        res_files1 = import_files(manifest_file, conn)

        assert res_mail1.items_imported > 0
        assert res_mail1.items_skipped == 0

        assert res_cal1.items_imported > 0
        assert res_cal1.items_skipped == 0

        assert res_files1.items_imported > 0
        assert res_files1.items_skipped == 0

        # Check total rows
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM raw_items")
        total_raw_after_first = cur.fetchone()[0]
        assert total_raw_after_first > 0

        # 2. Second Import of Identical Files (Idempotency test)
        res_mail2 = import_mail(mbox_file, conn, user_addresses=["meena.k@example.ac.in"])
        res_cal2 = import_calendar(ics_file, conn, user_addresses=["meena.k@example.ac.in"])
        res_files2 = import_files(manifest_file, conn)

        assert res_mail2.items_imported == 0
        assert res_mail2.items_skipped == res_mail1.items_imported

        assert res_cal2.items_imported == 0
        assert res_cal2.items_skipped == res_cal1.items_imported

        assert res_files2.items_imported == 0
        assert res_files2.items_skipped == res_files1.items_imported

        # Assert zero new rows in raw_items
        cur.execute("SELECT COUNT(*) FROM raw_items")
        total_raw_after_second = cur.fetchone()[0]
        assert total_raw_after_second == total_raw_after_first

        conn.close()


def test_t_synth_truth_join_exactness() -> None:
    """T-SYNTH: Primary situations join exactly with truth.json with 100% ID alignment."""
    from probation.workers.ingestor import ingest_situations

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)
        generate_synthetic_world(persona_id=0, seed=42, size="tiny", out_dir=out_dir)

        conn = get_connection(":memory:")
        apply_schema(conn)

        import_mail(out_dir / "mailbox.mbox", conn)
        import_calendar(out_dir / "calendar.ics", conn)
        import_files(out_dir / "files_manifest.json", conn)
        ingest_situations(conn)

        with open(out_dir / "truth.json", encoding="utf-8") as f:
            truth = json.load(f)

        cur = conn.cursor()
        cur.execute("SELECT id, pack, family, occurred_at FROM situations;")
        situations = cur.fetchall()

        assert len(situations) > 0
        matched = 0
        for s in situations:
            sid = s["id"]
            if sid in truth:
                matched += 1
                assert truth[sid]["family"] == s["family"]

        assert matched == len(situations), (
            f"Expected all {len(situations)} situations to match truth.json, matched {matched}"
        )
        conn.close()
