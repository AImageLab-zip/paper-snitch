"""Signup with email verification."""
import logging

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views import View

logger = logging.getLogger(__name__)
User = get_user_model()


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True, help_text="We send a link to this address to activate your account.")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


def send_verification_email(request, user) -> bool:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = request.build_absolute_uri(reverse("verify_email", args=[uid, token]))
    body = (
        f"Hi {user.username},\n\n"
        f"Confirm your email address to activate your PaperSnitch account:\n\n{link}\n\n"
        "If you did not sign up, ignore this email.\n"
    )
    try:
        send_mail("Activate your PaperSnitch account", body, settings.DEFAULT_FROM_EMAIL, [user.email])
        return True
    except Exception:
        logger.exception("Could not send the verification email to user %s", user.pk)
        return False


class SignUpView(View):
    template_name = "registration/signup.html"

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("profile")
        return render(request, self.template_name, {"form": SignUpForm()})

    def post(self, request):
        form = SignUpForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})
        user = form.save(commit=False)
        user.is_active = False  # activated by the emailed link
        user.save()
        sent = send_verification_email(request, user)
        return render(request, "registration/verify_sent.html", {"email": user.email, "sent": sent})


class VerifyEmailView(View):
    def get(self, request, uidb64, token):
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            user = None
        if user is None or not default_token_generator.check_token(user, token):
            return render(request, "registration/verify_invalid.html", status=400)
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=["is_active"])
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Your email is confirmed. Add your OpenAI API key to start analyzing papers.")
        return redirect("profile")


class ResendVerificationView(View):
    template_name = "registration/verify_resend.html"

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        email = (request.POST.get("email") or "").strip()
        user = User.objects.filter(email__iexact=email, is_active=False).first()
        if user:
            send_verification_email(request, user)
        # Same answer either way, so the form doesn't reveal which emails are registered
        return render(request, "registration/verify_sent.html", {"email": email, "sent": True})
