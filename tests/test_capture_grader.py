"""The capture-quality grader is graded (miniature D2 philosophy): a planted
failure must fail, or CI breaks — a grader that stops detecting misses is the
dangerous kind of green."""

from grade_capture import grade_all, grade_scene, normalize

SCENE = {
    "id": "s1",
    "app": "Preview",
    "setup": "-",
    "must": ["interruption budget", "three pulses per day"],
    "forbid": ["column two sentinel", "••••••••"],
}

GOOD_TEXT = (
    "The pulse enforces a strict interruption\nbudget: at most three nudges per run and\n"
    "six per day. jotd runs three pulses\nper day by default."
)


def cap(text):
    return {"text": text, "app": "Preview", "title": "x.pdf", "method": "region"}


def test_normalize_absorbs_ocr_noise_not_misreads():
    assert normalize("Interruption—BUDGET!") == "interruption budget"
    assert normalize("ﬁle") == "file"  # NFKC ligature fold
    assert "interruption budget" in normalize(GOOD_TEXT)  # across a line break
    assert "interruption budget" not in normalize("lnterruption budget")  # I->l misread counts


def test_good_capture_passes():
    result = grade_scene(SCENE, cap(GOOD_TEXT))
    assert result["passed"] is True and result["method"] == "region"


def test_planted_missing_phrase_fails():
    result = grade_scene(SCENE, cap("The pulse enforces a strict interruption budget."))
    assert result["passed"] is False
    assert result["missing"] == ["three pulses per day"]


def test_forbid_word_phrase_detects_column_bleed():
    result = grade_scene(SCENE, cap(GOOD_TEXT + "\nCOLUMN TWO SENTINEL. oranges bicycle"))
    assert result["passed"] is False
    assert result["leaked"] == ["column two sentinel"]


def test_symbol_forbid_checks_raw_text():
    leaked = grade_scene(SCENE, cap(GOOD_TEXT + "\nPassword ••••••••••"))
    assert leaked["leaked"] == ["••••••••"]
    redacted = grade_scene(SCENE, cap(GOOD_TEXT + "\nauth ok"))
    assert redacted["passed"] is True


def test_capture_error_fails_with_reason():
    assert grade_scene(SCENE, None)["reason"] == "capture-error"
    assert grade_scene(SCENE, {"app": "x"})["reason"] == "capture-error"


def test_gate_math():
    scenes = [dict(SCENE, id=f"s{i}", forbid=[]) for i in range(4)]
    captures = {f"s{i}": cap(GOOD_TEXT) for i in range(3)} | {"s3": cap("nothing relevant")}
    summary = grade_all(scenes, captures)
    assert summary["passed"] == 3 and summary["overall"] is False  # 0.75 < 0.85
    captures["s3"] = cap(GOOD_TEXT)
    assert grade_all(scenes, captures)["overall"] is True
