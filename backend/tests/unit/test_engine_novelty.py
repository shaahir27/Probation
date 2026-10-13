"""Test T-NOVELTY: K-NN novelty detector for out-of-distribution detection.

Authority: docs/ENGINE_SPEC.md section 5, and docs/TEST_PLAN.md T-NOVELTY.
"""

from probation.engine.novelty import NoveltyDetector


def test_t_novelty_fewer_than_k_plus_one() -> None:
    """Fewer than NOVELTY_K + 1 training rows returns novel=True."""
    detector = NoveltyDetector(k=5)
    texts = ["Course lecture update on machine learning", "Homework 2 deadline extended"]
    detector.fit(texts)

    assert not detector.is_fitted
    is_novel, dist = detector.score("Course lecture update")
    assert is_novel is True
    assert dist == 1.0


def test_t_novelty_in_distribution_vs_far_outlier() -> None:
    """Known in-distribution texts are not novel; anomalous far synthetic text is novel."""
    detector = NoveltyDetector(k=3, percentile=90.0)

    # Training corpus of university academic emails
    corpus = [
        "Assignment grading completed by professor and assistant",
        "Assignment submission deadline reminder for students",
        "Assignment feedback and grading notes posted",
        "Lecture notes and course discussion for students",
        "Lecture slides posted for course syllabus",
        "Course syllabus and lecture schedule updated",
        "Lab report guidelines for assignment project",
        "Lab submission and grading rubric details",
        "Midterm examination and grading criteria announced",
        "Office hours for course and assignment questions",
    ]

    detector.fit(corpus)
    assert detector.is_fitted
    assert detector.threshold > 0.0

    # 1. In-distribution point
    in_dist = "Assignment 2 grading notes and feedback from teaching assistant"
    is_novel_in, dist_in = detector.score(in_dist)
    assert is_novel_in is False, (
        f"Expected in-distribution not novel, got dist={dist_in}, thresh={detector.threshold}"
    )

    # 2. Far synthetic anomaly completely outside university domain
    far_anomaly = "URGENT Wire transfer lottery prize claiming notification gold bullion deposit"
    is_novel_out, dist_out = detector.score(far_anomaly)
    assert is_novel_out is True, (
        f"Expected outlier to be novel, got dist={dist_out}, thresh={detector.threshold}"
    )
    assert dist_out > dist_in
