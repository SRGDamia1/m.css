"""Tests for HTML and Jinja template filename compatibility."""

import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, TemplateNotFound

from doxygen import make_template_loader


class TemplateLoader(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    @staticmethod
    def _write(directory, name, contents):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(contents, encoding='utf-8')

    @staticmethod
    def _environment(searchpaths):
        return Environment(
            loader=make_template_loader(searchpaths, '.html.jinja2'))

    def test_suffixed_name_falls_back_to_plain_html(self):
        templates = self.root / 'templates'
        self._write(templates, 'page.html', 'plain html')

        rendered = self._environment([templates]).get_template(
            'page.html.jinja2').render()

        self.assertEqual(rendered, 'plain html')

    def test_plain_name_falls_back_to_suffixed_template(self):
        templates = self.root / 'templates'
        self._write(templates, 'page.html.jinja2', 'jinja template')

        rendered = self._environment([templates]).get_template(
            'page.html').render()

        self.assertEqual(rendered, 'jinja template')

    def test_custom_directory_fallback_precedes_default_exact_match(self):
        custom = self.root / 'custom'
        default = self.root / 'default'
        self._write(custom, 'page.html.jinja2', 'custom template')
        self._write(default, 'page.html', 'default template')

        rendered = self._environment([custom, default]).get_template(
            'page.html').render()

        self.assertEqual(rendered, 'custom template')

    def test_missing_template_preserves_requested_name(self):
        templates = self.root / 'templates'
        templates.mkdir()

        with self.assertRaisesRegex(TemplateNotFound, 'missing.html.jinja2'):
            self._environment([templates]).get_template(
                'missing.html.jinja2')


if __name__ == '__main__':
    unittest.main()
