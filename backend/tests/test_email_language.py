import os
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from string import Formatter

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from core.email_events import release_event, season_title, streaming_event
from core.email_translations import EMAIL_TRANSLATIONS
from core.notifications import send_rating_digests
from models.base import MediaType
from models.users import UserSettings
from routers import auth
import schemas


class EventTranslationTests(unittest.TestCase):
    def test_release_dates_and_streaming_provider_names(self):
        day = date(2026, 10, 18)
        expected = {
            "en": "Theatrical release date reached: October 18, 2026",
            "de": "Kinostart erreicht: 18. Oktober 2026",
            "fr": "Date de sortie en salle atteinte : 18 octobre 2026",
            "pt-PT": "Data de estreia nos cinemas atingida: 18 de outubro de 2026",
        }
        for language, result in expected.items():
            with self.subTest(language=language):
                self.assertEqual(release_event(day, language), result)
                self.assertIn("Netflix & More", streaming_event(["Netflix & More"], language))
        self.assertEqual(season_title("Example", 2, "de"), "Example (Staffel 2)")
        self.assertEqual(release_event(day, None), expected["en"])

    def test_translation_catalogs_have_identical_keys_and_placeholders(self):
        english = EMAIL_TRANSLATIONS["en"]
        for locale, messages in EMAIL_TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertEqual(messages.keys(), english.keys())
                for key, text in english.items():
                    fields = lambda value: sorted(field for _, field, _, _ in Formatter().parse(value) if field)
                    self.assertEqual(fields(messages[key]), fields(text), (locale, key))


class EmailTemplateTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_email_type_uses_the_recipient_language(self):
        from core import email

        expectations = {
            "en": ("Activate your Scrob account", "Reset your Scrob password", "New friend request", "Watchlist update"),
            "de": ("Aktiviere dein Scrob-Konto", "Setze dein Scrob-Passwort zurück", "Neue Freundschaftsanfrage", "Watchlist-Aktualisierung"),
            "fr": ("Activez votre compte Scrob", "Réinitialisez votre mot de passe Scrob", "Nouvelle demande d’ami", "Mise à jour de la liste à voir"),
            "pt-PT": ("Ative a sua conta Scrob", "Reponha a sua palavra-passe Scrob", "Novo pedido de amizade", "Atualização da lista para ver"),
        }
        for language, (activation, reset, request, watchlist) in expectations.items():
            with self.subTest(language=language), patch("core.email.send_email", new_callable=AsyncMock) as send:
                await email.send_activation_email("a@example.com", "token", language=language)
                self.assertEqual(send.await_args.args[1], activation)
                await email.send_email_change_email("a@example.com", "token", language=language)
                self.assertIn(email.email_text(language, "email_change_heading"), send.await_args.args[2])
                await email.send_password_reset_email("a@example.com", "token", language=language)
                self.assertEqual(send.await_args.args[1], reset)
                await email.send_friend_request_email("a@example.com", "A & B", language=language)
                self.assertIn(request, send.await_args.args[2])
                self.assertIn("A &amp; B", send.await_args.args[2])
                await email.send_friend_media_share_email("a@example.com", "A", "<Film>", "/movie/1", 8.5, "<comment>", language=language)
                self.assertIn(email.email_text(language, "share_heading"), send.await_args.args[2])
                self.assertIn("&lt;Film&gt;", send.await_args.args[2])
                self.assertIn("&lt;comment&gt;", send.await_args.args[2])
                for items in [[("A", "Film", 8.5)], [("A", "Film", 8.5), ("B", "Film", None)]]:
                    await email.send_rating_digest_email("a@example.com", items, language=language)
                    key = "digest_subject_one" if len(items) == 1 else "digest_subject_many"
                    self.assertEqual(send.await_args.args[1], email.email_text(language, key).format(count=len(items)))
                await email.send_watchlist_alert_email("a@example.com", "Film", "/movie/1", ["Netflix & More"], language=language)
                self.assertIn(watchlist, send.await_args.args[2])
                self.assertIn("Netflix &amp; More", send.await_args.args[2])
                self.assertIn(email.email_text(language, "fallback_link"), send.await_args.args[2])

    def test_plain_text_decodes_escaped_user_content(self):
        from core.email import _html_to_text
        self.assertIn("A & B <Film>", _html_to_text("<p>A &amp; B &lt;Film&gt;</p>"))


class AuthEmailLanguageTests(unittest.IsolatedAsyncioTestCase):
    async def test_registration_saves_and_uses_selected_language(self):
        results = [
            SimpleNamespace(scalar_one=lambda: 0),
            SimpleNamespace(scalar_one_or_none=lambda: None),
            SimpleNamespace(scalar_one=lambda: 0),
        ]
        db = MagicMock()
        db.execute = AsyncMock(side_effect=results)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()

        async def flush():
            db.add.call_args_list[0].args[0].id = 42

        db.flush = AsyncMock(side_effect=flush)
        user = schemas.UserCreate(email="test@example.com", username="test", password="secret", ui_language="de")
        with patch.object(auth.app_settings, "require_email_validation", True), \
             patch.object(auth, "send_activation_email", new_callable=AsyncMock) as send:
            await auth.register.__wrapped__(SimpleNamespace(), user, db)
        settings = next(call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], UserSettings))
        self.assertEqual((settings.user_id, settings.ui_language), (42, "de"))
        self.assertEqual(send.await_args.kwargs["language"], "de")

    async def test_password_reset_prefers_recipient_language_to_browser(self):
        user = SimpleNamespace(id=42, email="test@example.com")
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[SimpleNamespace(scalar_one_or_none=lambda: user), None])
        db.commit = AsyncMock()
        body = schemas.ForgotPasswordRequest(email="test@example.com", ui_language="fr")
        with patch.object(auth.app_settings, "smtp_address", "smtp.example.com"), \
             patch.object(auth, "get_user_email_language", new_callable=AsyncMock, return_value="de"), \
             patch.object(auth, "send_password_reset_email", new_callable=AsyncMock) as send:
            await auth.forgot_password.__wrapped__(SimpleNamespace(), body, db)
        self.assertEqual(send.await_args.kwargs["language"], "de")

    async def test_password_reset_uses_page_language_without_account_preference(self):
        user = SimpleNamespace(id=42, email="test@example.com")
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[SimpleNamespace(scalar_one_or_none=lambda: user), None])
        db.commit = AsyncMock()
        body = schemas.ForgotPasswordRequest(email="test@example.com", ui_language="fr")
        with patch.object(auth.app_settings, "smtp_address", "smtp.example.com"), \
             patch.object(auth, "get_user_email_language", new_callable=AsyncMock, return_value=None), \
             patch.object(auth, "send_password_reset_email", new_callable=AsyncMock) as send:
            await auth.forgot_password.__wrapped__(SimpleNamespace(), body, db)
        self.assertEqual(send.await_args.kwargs["language"], "fr")


class DigestLanguageTests(unittest.IsolatedAsyncioTestCase):
    async def test_digest_uses_recipient_language_for_season_and_email(self):
        note = SimpleNamespace(id=1, user_id=7, actor_id=8, media_id=9, is_read=False, season_number=2, rating=8)
        recipient = SimpleNamespace(id=7, email="recipient@example.com", email_confirmed=True)
        actor = SimpleNamespace(id=8, display_name="Friend")
        media = SimpleNamespace(id=9, title="Example", media_type=MediaType.series, show=None)

        def rows(values):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: values))

        db = SimpleNamespace(
            execute=AsyncMock(side_effect=[rows([note]), rows([recipient, actor]), rows([media]), rows([]), None]),
            commit=AsyncMock(),
        )
        with patch("core.email.email_enabled", return_value=True), \
             patch("core.notifications.get_user_email_language", new_callable=AsyncMock, return_value="de"), \
             patch("core.email.send_rating_digest_email", new_callable=AsyncMock) as send:
            self.assertEqual(await send_rating_digests(db), 1)
        send.assert_awaited_once_with(recipient.email, [("Friend", "Example (Staffel 2)", 8)], language="de")
