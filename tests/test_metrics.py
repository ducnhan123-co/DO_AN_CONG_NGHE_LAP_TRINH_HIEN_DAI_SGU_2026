import json
import unicodedata

from llm.src.metrics import (cer, edit_counts, evaluate_pages, main,
                             normalize_text, page_error_rate, split_pages, wer)


def test_cer_counts_substitution_deletion_insertion():
    assert cer("abc", "abd") == 1 / 3
    assert cer("abc", "ab") == 1 / 3
    assert cer("abc", "abxc") == 1 / 3
    counts = edit_counts("abc", "abxc")
    assert (counts.substitutions, counts.deletions, counts.insertions) == (0, 0, 1)


def test_wer_uses_whitespace_tokens():
    assert wer("xin chào bạn", "xin chào") == 1 / 3
    assert wer("một hai ba", "một 2 ba") == 1 / 3


def test_unicode_nfc_makes_decomposed_and_precomposed_equal():
    decomposed = unicodedata.normalize("NFD", "Nguyễn")
    assert normalize_text(decomposed) == normalize_text("Nguyễn")
    assert cer(decomposed, "Nguyễn") == 0


def test_page_error_rate_is_strict_by_default():
    pairs = [("abc", "abc"), ("abc", "abd")]
    assert page_error_rate(pairs) == 0.5
    assert page_error_rate(pairs, threshold=1.0) == 0.0


def test_evaluate_pages_uses_micro_average_and_reports_pages():
    result = evaluate_pages([("abc", "abc"), ("abc", "abd")], names=["p1", "p2"])
    assert result.n_pages == 2
    assert result.n_pages_with_error == 1
    assert result.per == 0.5
    assert result.page_exact_match_rate == 0.5
    assert result.cer == 1 / 6
    assert [p.name for p in result.pages] == ["p1", "p2"]


def test_strip_math_keeps_text_metrics_separate():
    ref = "Cho $x^2$ là bình phương."
    hyp = "Cho $x^3$ là bình phương."
    assert cer(ref, hyp) > 0
    assert cer(normalize_text(ref, strip_math=True),
               normalize_text(hyp, strip_math=True)) == 0


def test_split_pages_by_form_feed():
    assert split_pages("a\fb\fc") == ["a", "b", "c"]
    assert split_pages("a\nb") == ["a\nb"]


def test_cli_writes_json(tmp_path, capsys):
    ref = tmp_path / "ref"
    hyp = tmp_path / "hyp"
    ref.mkdir()
    hyp.mkdir()
    (ref / "bai1.txt").write_text("Xin chào thế giới", encoding="utf-8")
    (hyp / "bai1.md").write_text("Xin chào thế giới", encoding="utf-8")
    out_json = tmp_path / "metrics.json"
    code = main(["--ref", str(ref), "--hyp", str(hyp), "--json", str(out_json)])
    assert code == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["n_pages"] == 1 and data["cer"] == 0 and data["per"] == 0
    assert "PER" in capsys.readouterr().out
