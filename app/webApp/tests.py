"""Accounts, per-user OpenAI keys, permissions and visibility."""
import os
import re
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from webApp.models import LLMModelConfig, Paper, UserAPIKey
from webApp.permissions import can_view_run, visible_papers, visible_runs
from webApp.services import credentials
from workflow_engine.models import WorkflowDefinition, WorkflowNode, WorkflowRun

User = get_user_model()
TEST_FERNET = "x4bqY0Y6m0sJmW8vQyR2Kz3dVv6l0b2R9n1aXo8cT1Q="
USER_KEY = "sk-user-" + "a" * 40
SERVER_KEY = "sk-server-" + "b" * 40
MEDIA = tempfile.mkdtemp(prefix="ps-test-media-")

ENV = {"FIELD_ENCRYPTION_KEY": TEST_FERNET, "OPENAI_API_KEY": SERVER_KEY}


@override_settings(MEDIA_ROOT=MEDIA, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class Base(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._env = mock.patch.dict(os.environ, ENV)
        cls._env.start()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._env.stop()

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user("staff", "s@x.org", "pw", is_staff=True)
        cls.alice = User.objects.create_user("alice", "a@x.org", "pw")
        cls.bob = User.objects.create_user("bob", "b@x.org", "pw")
        UserAPIKey.objects.create(
            user=cls.alice, encrypted_key=credentials.encrypt(USER_KEY),
            masked=credentials.mask(USER_KEY), verified_at=timezone.now(),
        )
        LLMModelConfig.objects.get_or_create(
            model_key="gpt4o",
            defaults=dict(visual_name="GPT-4o", model="gpt-4o", api_key_env_var="OPENAI_API_KEY",
                          base_url="https://api.openai.com/v1", is_active=True),
        )
        cls.wf = WorkflowDefinition.objects.create(
            name="paper_processing_with_reproducibility", version=9, is_active=True,
            dag_structure={"nodes": [], "edges": [], "workflow_handler": {
                "module": "webApp.services.graphs.paper_processing_workflow", "function": "execute_workflow"}},
        )
        cls.public_paper = Paper.objects.create(title="Public paper")
        cls.private_paper = Paper.objects.create(title="Alice private upload", owner=cls.alice, is_public=False)

    def run_for(self, paper, user, public, **extra):
        return WorkflowRun.objects.create(
            workflow_definition=self.wf, paper=paper, created_by=user, is_public=public,
            status=extra.pop("status", "completed"), input_data=extra.pop("input_data", {"model": "gpt-4o"}), **extra,
        )


class CredentialsTests(Base):
    def test_encrypt_round_trip_and_mask(self):
        token = credentials.encrypt(USER_KEY)
        self.assertNotIn(USER_KEY, token)
        self.assertEqual(credentials.decrypt(token), USER_KEY)
        self.assertEqual(credentials.mask(USER_KEY), "sk-…aaaa")

    def test_missing_encryption_key_is_an_error(self):
        with mock.patch.dict(os.environ, {"FIELD_ENCRYPTION_KEY": ""}):
            with self.assertRaises(ImproperlyConfigured):
                credentials.encrypt("sk-whatever")

    def test_redact(self):
        text = f"Incorrect API key provided: {USER_KEY[:20]}. Check it."
        self.assertNotIn(USER_KEY[:20], credentials.redact(text))
        self.assertIn("sk-…[redacted]", credentials.redact(text))

    def test_resolve_rules(self):
        self.assertEqual(credentials.resolve_openai_key(None), SERVER_KEY)
        self.assertEqual(credentials.resolve_openai_key(self.staff), SERVER_KEY)
        self.assertEqual(credentials.resolve_openai_key(self.alice), USER_KEY)
        with self.assertRaises(credentials.MissingAPIKey):
            credentials.resolve_openai_key(self.bob)

    def test_stored_errors_are_redacted(self):
        run = self.run_for(self.public_paper, self.alice, False, error_message=f"401 for key {USER_KEY}")
        run.refresh_from_db()
        self.assertNotIn(USER_KEY, run.error_message)


class VisibilityTests(Base):
    def setUp(self):
        self.staff_run = self.run_for(self.public_paper, self.staff, True)
        self.alice_private = self.run_for(self.public_paper, self.alice, False)
        self.alice_public_on_private_paper = self.run_for(self.private_paper, self.alice, True)

    def ids(self, user):
        from django.contrib.auth.models import AnonymousUser
        return set(visible_runs(WorkflowRun.objects.all(), user or AnonymousUser()).values_list("id", flat=True))

    def test_matrix(self):
        everything = {self.staff_run.id, self.alice_private.id, self.alice_public_on_private_paper.id}
        self.assertEqual(self.ids(None), {self.staff_run.id})
        self.assertEqual(self.ids(self.bob), {self.staff_run.id})
        self.assertEqual(self.ids(self.alice), everything)
        self.assertEqual(self.ids(self.staff), everything)
        self.assertFalse(can_view_run(self.alice_public_on_private_paper, self.bob))
        self.assertEqual(set(visible_papers(Paper.objects.all(), self.bob)), {self.public_paper})

    def test_pages_hide_private_things(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse("paper_detail", args=[self.private_paper.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("paper_pdf", args=[self.private_paper.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("demo:report", args=[self.alice_private.id])).status_code, 404)
        page = self.client.get(reverse("paper_detail", args=[self.public_paper.id]) + f"?workflow_run={self.alice_private.id}")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(str(self.alice_private.id), page.content.decode())

    def test_owner_toggles_visibility(self):
        url = reverse("run_visibility", args=[self.alice_private.id])
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(url, {"public": "true"}).status_code, 403)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.post(url, {"public": "true"}).json()["is_public"], True)

    def test_owner_gets_private_pdf(self):
        self.private_paper.file.save("private/t/paper.pdf", SimpleUploadedFile("p.pdf", b"%PDF-1.4 test"))
        self.client.force_login(self.alice)
        response = self.client.get(reverse("paper_pdf", args=[self.private_paper.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 test")
        self.client.logout()
        self.assertEqual(self.client.get(reverse("paper_pdf", args=[self.private_paper.id])).status_code, 404)


@mock.patch("webApp.tasks.process_paper_workflow_task")
class RunPermissionTests(Base):
    def post(self, user, **data):
        from webApp.tasks import process_paper_workflow_task as task
        task.delay.return_value.id = "task-id"
        if user:
            self.client.force_login(user)
        return self.client.post(
            reverse("rerun_workflow", args=[self.public_paper.id]),
            {"workflow_type": str(self.wf.id), "model": "gpt-4o", **data},
        )

    def test_anonymous_and_keyless_users_cannot_run(self, task):
        self.assertEqual(self.post(None).status_code, 401)
        response = self.post(self.bob)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.json()["needs_api_key"])
        task.delay.assert_not_called()

    def test_user_run_passes_only_the_user_id(self, task):
        self.assertEqual(self.post(self.alice).status_code, 200)
        kwargs = task.delay.call_args.kwargs
        self.assertEqual(kwargs["user_id"], self.alice.id)
        self.assertFalse(kwargs["is_public"])  # users default to private
        self.assertNotIn(USER_KEY, repr(task.delay.call_args))

    def test_user_cannot_pick_unlisted_model(self, task):
        self.post(self.alice, model="gpt-5-pro")
        self.assertEqual(task.delay.call_args.kwargs["model"], "gpt-4o")

    def test_staff_default_public(self, task):
        self.post(self.staff)
        self.assertTrue(task.delay.call_args.kwargs["is_public"])

    def test_bulk_endpoints_are_staff_only(self, task):
        from webApp.models import Conference
        conf = Conference.objects.create(name="MICCAI", year=2026)
        self.client.force_login(self.alice)
        for name in ("bulk_rerun_workflows", "bulk_stop_workflows", "bulk_rerun_preview"):
            response = self.client.post(reverse(name, args=[conf.id]))
            self.assertEqual(response.status_code, 403, name)

    def test_node_rerun_requires_ownership(self, task):
        run = self.run_for(self.public_paper, self.staff, True)
        node = WorkflowNode.objects.create(workflow_run=run, node_id="final_aggregation", node_type="python",
                                           handler="x", status="completed")
        for user, code in ((None, 401), (self.alice, 403)):
            self.client.logout()
            if user:
                self.client.force_login(user)
            for name in ("rerun_single_node", "rerun_from_node"):
                self.assertEqual(self.client.post(reverse(name, args=[node.id])).status_code, code, name)

    def test_annotator_is_staff_only(self, task):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get("/annotator/documents/").status_code, 302)


class KeyThreadingTests(Base):
    def test_worker_resolves_the_users_key(self):
        from webApp import tasks

        seen = {}

        async def fake_execute(**kwargs):
            seen.update(kwargs)
            return {"success": True}

        with mock.patch("webApp.services.graphs.paper_processing_workflow.execute_workflow", fake_execute):
            tasks.process_paper_workflow_task.run(
                paper_id=self.public_paper.id, force_reprocess=False, model="gpt-4o",
                workflow_id=str(self.wf.id), user_id=self.alice.id, is_public=False,
            )
        self.assertEqual(seen["openai_api_key"], USER_KEY)
        self.assertTrue(seen["force_reprocess"])  # no shared cache for user-billed runs

    def test_keyless_user_is_refused_in_the_worker(self):
        from webApp import tasks

        result = tasks.process_paper_workflow_task.run(paper_id=self.public_paper.id, user_id=self.bob.id)
        self.assertFalse(result["success"])

    def test_scheduler_skips_langgraph_runs(self):
        from workflow_engine.services.orchestrator import WorkflowOrchestrator

        langgraph = self.run_for(self.public_paper, self.alice, False, status="running",
                                 input_data={"model": "gpt-4o", "executor": "langgraph"})
        WorkflowNode.objects.create(workflow_run=langgraph, node_id="a", node_type="python", handler="x", status="ready")
        self.assertIsNone(WorkflowOrchestrator().claim_ready_task())

        legacy = self.run_for(self.public_paper, None, True, status="running", input_data={"model": "gpt-5"})
        node = WorkflowNode.objects.create(workflow_run=legacy, node_id="b", node_type="python", handler="x", status="ready")
        self.assertEqual(WorkflowOrchestrator().claim_ready_task().id, node.id)


class APIKeyViewTests(Base):
    def test_save_validates_and_encrypts(self):
        self.client.force_login(self.bob)
        raw = "sk-bob-" + "c" * 40
        with mock.patch("webApp.services.credentials.validate_openai_key", return_value=(False, "Invalid key")):
            self.client.post(reverse("api_key"), {"api_key": raw})
        self.assertFalse(UserAPIKey.objects.filter(user=self.bob).exists())
        with mock.patch("webApp.services.credentials.validate_openai_key", return_value=(True, "")):
            self.client.post(reverse("api_key"), {"api_key": raw})
        stored = UserAPIKey.objects.get(user=self.bob)
        self.assertNotIn(raw, stored.encrypted_key)
        self.assertEqual(credentials.resolve_openai_key(self.bob), raw)
        profile = self.client.get(reverse("profile")).content.decode()
        self.assertNotIn(raw, profile)
        self.assertIn(stored.masked, profile)
        self.client.post(reverse("api_key"), {"action": "delete"})
        self.assertFalse(UserAPIKey.objects.filter(user=self.bob).exists())


class UploadTests(Base):
    @mock.patch("webApp.tasks.ingest_uploaded_paper_task")
    def test_upload_is_private_and_deduplicated(self, ingest):
        self.client.force_login(self.alice)
        pdf = lambda: SimpleUploadedFile("my paper.pdf", b"%PDF-1.7 hello", content_type="application/pdf")
        self.client.post(reverse("analyze_upload"), {"pdf": pdf(), "model": "gpt-4o"})
        self.client.post(reverse("analyze_upload"), {"pdf": pdf(), "model": "gpt-4o"})
        papers = Paper.objects.filter(owner=self.alice).exclude(id=self.private_paper.id)
        self.assertEqual(papers.count(), 1)
        paper = papers.get()
        self.assertFalse(paper.is_public)
        self.assertTrue(paper.file.name.startswith("private/"))
        self.assertEqual(ingest.delay.call_count, 2)
        self.assertEqual(ingest.delay.call_args.args[1], self.alice.id)

    def test_rejects_non_pdf_and_keyless(self):
        self.client.force_login(self.alice)
        self.client.post(reverse("analyze_upload"), {"pdf": SimpleUploadedFile("x.pdf", b"hello")})
        self.client.force_login(self.bob)
        response = self.client.post(reverse("analyze_upload"), {"pdf": SimpleUploadedFile("x.pdf", b"%PDF-1.4")})
        self.assertRedirects(response, reverse("profile"), fetch_redirect_response=False)
        self.assertFalse(Paper.objects.exclude(id__in=[self.public_paper.id, self.private_paper.id]).exists())


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SignupTests(TestCase):
    def signup(self, **over):
        data = {"username": "carol", "email": "carol@x.org", "password1": "a-Long-pass-123", "password2": "a-Long-pass-123"}
        data.update(over)
        return self.client.post(reverse("signup"), data)

    def test_signup_verify_login(self):
        self.signup()
        user = User.objects.get(username="carol")
        self.assertFalse(user.is_active)
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r"https?://\S+", mail.outbox[0].body).group(0)
        self.assertFalse(self.client.login(username="carol", password="a-Long-pass-123"))
        response = self.client.get(link)
        self.assertRedirects(response, reverse("profile"), fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(self.client.get(link).status_code, 400)  # token is single-use once active... and logged in

    def test_duplicate_email_and_bad_token(self):
        self.signup()
        self.signup(username="carol2", email="CAROL@x.org")
        self.assertFalse(User.objects.filter(username="carol2").exists())
        self.assertEqual(self.client.get(reverse("verify_email", args=["MQ", "nope"])).status_code, 400)

    def test_resend_does_not_reveal_accounts(self):
        self.signup()
        mail.outbox.clear()
        a = self.client.post(reverse("resend_verification"), {"email": "carol@x.org"})
        b = self.client.post(reverse("resend_verification"), {"email": "nobody@x.org"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(a.status_code, b.status_code)

    def test_password_reset_page_renders(self):
        page = self.client.get(reverse("password_reset"))
        self.assertContains(page, "Reset your password")
