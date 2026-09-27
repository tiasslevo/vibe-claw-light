from html.parser import HTMLParser
import unittest

from vibe_claw_light.formatting import (
    format_messages, md_to_telegram_html, plain_chunks, utf16_length,
)


class TelegramHTML(HTMLParser):
    """Check balanced supported markup and measure the decoded message."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.visible = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        assert tag in {"b", "i", "s", "a", "code", "pre", "blockquote"}, tag
        if tag == "code":
            assert all(parent == "pre" for parent in self.stack)
        if tag == "a":
            assert all(parent in {"b", "i", "s"} for parent in self.stack)
            self.links.append(dict(attrs)["href"])
        self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack and self.stack.pop() == tag, tag

    def handle_data(self, data):
        self.visible.append(data)

    def read(self, text):
        self.feed(text)
        self.close()
        assert not self.stack
        return "".join(self.visible)


class FormattingTests(unittest.TestCase):
    def test_common_markdown_is_readable_in_telegram(self):
        source = "# Le résultat\n\n**Prêt** et *simple*, _utile_, ~~ancien~~.\n- Une idée\n- [x] Terminé\n1. Suivant"
        rendered = md_to_telegram_html(source)
        self.assertIn("<b>Le résultat</b>", rendered)
        self.assertIn("<b>Prêt</b>", rendered)
        self.assertIn("<i>simple</i>", rendered)
        self.assertIn("<i>utile</i>", rendered)
        self.assertIn("<s>ancien</s>", rendered)
        self.assertIn("• Une idée\n☑ Terminé\n1. Suivant", rendered)
        self.assertNotIn("**", TelegramHTML().read(rendered))

    def test_code_preserves_markdown_and_escapes_html(self):
        source = "Voici `a_b < 3 && x` :\n```python\nprint('<b>**exact**</b>')\n```"
        rendered = md_to_telegram_html(source)
        self.assertIn("<code>a_b &lt; 3 &amp;&amp; x</code>", rendered)
        self.assertIn('<pre><code class="language-python">', rendered)
        self.assertIn("print('&lt;b&gt;**exact**&lt;/b&gt;')", rendered)
        self.assertEqual(TelegramHTML().read(rendered), "Voici a_b < 3 && x :\nprint('<b>**exact**</b>')")

    def test_styles_are_suspended_around_nested_code(self):
        rendered = md_to_telegram_html("**Texte *italique* avec `code` et fin**")
        self.assertIn("<b>Texte <i>italique</i> avec </b><code>code</code><b> et fin</b>", rendered)
        self.assertEqual(TelegramHTML().read(rendered), "Texte italique avec code et fin")

    def test_raw_html_and_entities_are_displayed_literally(self):
        source = '<script>alert("x")</script> &lt; faux <b>gras</b>'
        rendered = md_to_telegram_html(source)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<b>", rendered)
        self.assertIn("&amp;lt;", rendered)
        self.assertEqual(TelegramHTML().read(rendered), source)

    def test_safe_links_escape_attributes_and_keep_parentheses(self):
        source = '[Documentation](https://example.org/a_(b)?a=1&b="ok")'
        rendered = md_to_telegram_html(source)
        parser = TelegramHTML()
        self.assertEqual(parser.read(rendered), "Documentation")
        self.assertEqual(parser.links, ['https://example.org/a_(b)?a=1&b="ok"'])
        self.assertIn("&quot;ok&quot;", rendered)
        self.assertIn("&amp;b=", rendered)
        self.assertEqual(format_messages(source)[0].plain,
                         'Documentation (https://example.org/a_(b)?a=1&b="ok")')

    def test_unsafe_links_never_create_html_links(self):
        for target in ("javascript:alert(1)", "data:text/html,test", "file:///private/test",
                       "https://user:password@example.org", "https://example.org/ bad"):
            with self.subTest(target=target):
                rendered = md_to_telegram_html(f"[Lire]({target})")
                self.assertEqual(rendered, "Lire")
                self.assertEqual(TelegramHTML().read(rendered), "Lire")

    def test_quotes_and_tables_use_supported_mobile_friendly_markup(self):
        source = "> Une **citation**\n> Suite\n\n| Nom | État |\n| --- | --- |\n| Vocal | Prêt |\n| Rappel | En cours |"
        rendered = md_to_telegram_html(source)
        self.assertIn("<blockquote>Une <b>citation</b>\nSuite</blockquote>", rendered)
        self.assertIn("<b>Vocal</b>\nÉtat : Prêt\n\n<b>Rappel</b>\nÉtat : En cours", rendered)
        self.assertNotIn("| --- |", rendered)
        TelegramHTML().read(rendered)

    def test_quote_links_and_code_follow_telegram_nesting_restrictions(self):
        rendered = md_to_telegram_html("> Un **[lien](https://example.org)** et du `code`.")
        self.assertEqual(TelegramHTML().read(rendered), "Un lien et du code.")
        self.assertIn('</blockquote><b><a href="https://example.org">lien</a></b><blockquote>', rendered)
        self.assertIn("</blockquote><code>code</code><blockquote>", rendered)

    def test_unclosed_fence_remains_code_and_snake_case_remains_plain(self):
        self.assertEqual(md_to_telegram_html("un_fichier_python"), "un_fichier_python")
        self.assertEqual(md_to_telegram_html(r"\*texte\*"), "*texte*")
        rendered = md_to_telegram_html("```\n<unfinished> **code**")
        self.assertEqual(rendered, "<pre>&lt;unfinished&gt; **code**</pre>")

    def test_long_messages_have_balanced_tags_and_unicode_limit(self):
        content = ("🐈 & <ok> mot " * 1200).rstrip()
        source = "**" + content + "**\n```python\n" + content + "\n```"
        chunks = format_messages(source)
        self.assertGreater(len(chunks), 5)
        decoded = []
        for chunk in chunks:
            visible = TelegramHTML().read(chunk.html)
            self.assertLessEqual(utf16_length(visible), 3500)
            self.assertTrue(visible)
            decoded.append(visible)
        self.assertEqual("".join(decoded), content + "\n" + content)

    def test_split_reopens_links_and_never_splits_an_entity(self):
        source = "[" + ("é🐈& " * 30) + "](https://example.org)"
        chunks = format_messages(source, limit=31)
        decoded = []
        for chunk in chunks:
            parser = TelegramHTML()
            decoded.append(parser.read(chunk.html))
            self.assertEqual(parser.links, ["https://example.org"])
            self.assertLessEqual(utf16_length(decoded[-1]), 31)
        self.assertEqual("".join(decoded), "é🐈& " * 30)

    def test_plain_chunks_preserve_text_and_utf16_boundaries(self):
        source = "abc " + "🐈" * 3500 + "\nfin"
        chunks = plain_chunks(source)
        self.assertEqual("".join(chunks), source)
        self.assertTrue(all(utf16_length(chunk) <= 3500 for chunk in chunks))

    def test_empty_input_and_unsupported_markup_do_not_break_delivery(self):
        self.assertEqual(format_messages(""), [])
        for source in ("**sans fin", "[lien](incomplet", "<b>code", "```bad\"lang\ntexte\n```",
                       "****", "\x00invisible", "[a [b](https://example.org)](https://example.net)"):
            with self.subTest(source=source):
                TelegramHTML().read(md_to_telegram_html(source))


if __name__ == "__main__":
    unittest.main()
