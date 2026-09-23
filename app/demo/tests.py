from types import SimpleNamespace

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .matching import html_to_normalized_text, locate, normalize
from .timeline import _schedule


class MatchingTests(SimpleTestCase):
    DOC = html_to_normalized_text(
        "<html><style>.x{}</style><body>"
        '<div class="t">The models were trained with a batch<span class="_ _1"></span>size of 16 '
        "using the Adam optimi-</div><div>zer and a learning rate of 1e-4. The ﬁnal models were "
        "selected on the validation split.</div></body></html>"
    )

    def test_normalize_drops_spacing_punctuation_and_ligatures(self):
        self.assertEqual(normalize("The ﬁnal  Model-v2!"), "thefinalmodelv2")

    def test_exact_match_across_spans_and_hyphenation(self):
        status, coverage = locate(
            "trained with a batch size of 16 using the Adam optimizer", self.DOC
        )
        self.assertEqual((status, coverage), ("exact", 1.0))

    def test_partial_match_when_quote_is_stitched(self):
        quote = (
            "The models were trained with a batch size of 16 ... "
            "The final models were selected on the validation split."
        )
        status, coverage = locate(quote, self.DOC)
        self.assertEqual(status, "partial")
        self.assertGreater(coverage, 0.8)

    def test_paraphrase_is_missing(self):
        status, _ = locate("The paper does not report any statistical significance testing at all.", self.DOC)
        self.assertEqual(status, "missing")

    def test_short_quote(self):
        self.assertEqual(locate("Table 2", self.DOC)[0], "short")


class ScheduleTests(SimpleTestCase):
    def test_children_start_after_parents_and_total_is_scaled(self):
        nodes = {
            "a": SimpleNamespace(duration=4.0),
            "b": SimpleNamespace(duration=100.0),
            "c": SimpleNamespace(duration=0.01),
            "d": SimpleNamespace(duration=9.0),
        }
        edges = [
            {"from": "a", "to": "b"},
            {"from": "a", "to": "c"},
            {"from": "b", "to": "d"},
            {"from": "c", "to": "d"},
        ]
        times = _schedule(nodes, edges, target_duration=60)
        self.assertAlmostEqual(max(end for _, end in times.values()), 60)
        self.assertGreater(times["b"][0], times["a"][1])
        self.assertGreater(times["d"][0], times["b"][1])
        # Near-instant nodes stay visible.
        self.assertGreater(times["c"][1] - times["c"][0], 1.0)

    def test_real_schedule_is_critical_path(self):
        nodes = {"a": SimpleNamespace(duration=2.0), "b": SimpleNamespace(duration=5.0), "c": SimpleNamespace(duration=1.0)}
        edges = [{"from": "a", "to": "b"}, {"from": "a", "to": "c"}]
        times = _schedule(nodes, edges)
        self.assertEqual(max(end for _, end in times.values()), 7.0)


class UploadTests(TestCase):
    def test_rejects_non_pdf(self):
        upload = SimpleUploadedFile("notes.pdf", b"hello world", content_type="application/pdf")
        response = self.client.post(reverse("demo:upload"), {"pdf_file": upload})
        self.assertEqual(response.status_code, 400)

    def test_unknown_pdf_is_not_matched(self):
        upload = SimpleUploadedFile("other.pdf", b"%PDF-1.4 unknown", content_type="application/pdf")
        response = self.client.post(reverse("demo:upload"), {"pdf_file": upload})
        self.assertEqual(response.json(), {"matched": False})

    def test_landing_renders_without_scenarios(self):
        response = self.client.get(reverse("demo:landing"))
        self.assertContains(response, "prepare_demo --list")
