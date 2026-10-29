"""Regression tests for generated Markdown structure and code preservation."""

import pathlib
import unittest
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader


class Markdown(unittest.TestCase):
    def test_optional_rendering(self):
        templates = pathlib.Path(__file__).parents[1] / 'templates' / 'doxybook2'
        env = Environment(loader=FileSystemLoader(str(templates)),
                          trim_blocks=True, lstrip_blocks=True)
        macros = env.get_template('macros.md.jinja2').module
        for value in (None, '', env.undefined(name='missing')):
            with self.subTest(value=value):
                self.assertEqual(macros.render_if_exists(value, before='\n', after='\n'), '')
        self.assertEqual(macros.render_if_exists('One\nTwo'), 'One\nTwo')
        self.assertEqual(macros.render_if_exists('Text', before='\n', after='\n'), '\nText\n')
        for kind in ('dir', 'group', 'example'):
            with self.subTest(template=kind):
                compound = SimpleNamespace(name='Test', kind=kind, brief_markdown='',
                                           description_markdown='Visible description')
                rendered = env.get_template(kind + '.md.jinja2').render(compound=compound)
                self.assertIn('Visible description', rendered)

    def test_group_subheadings(self):
        templates = pathlib.Path(__file__).parents[1] / 'templates' / 'doxybook2'
        env = Environment(loader=FileSystemLoader(str(templates)),
                          trim_blocks=True, lstrip_blocks=True)
        template = env.get_template('class_members_tables.md.jinja2')

        def render(members):
            children = [(kind, SimpleNamespace(name=f'member{index}', kind='function' if kind == 'func' else kind,
                                   is_protected=protected, templates=[], params=[],
                                   type_markdown='void', brief_markdown='', markdown_url='', values=[]))
                        for index, (kind, protected) in enumerate(members)]
            return template.render(compound=dict(groups=[dict(name='Utilities', members=children)]))

        for kind in ('func', 'var', 'enum', 'typedef'):
            for protected in (False, True):
                with self.subTest(kind=kind, protected=protected):
                    result = render([(kind, protected), (kind, protected)])
                    self.assertIn('## Utilities', result)
                    self.assertNotIn('### ', result)
                    self.assertIn('member0', result)
                    self.assertIn('member1', result)

        result = render([('func', False), ('func', True)])
        self.assertIn('### Public Functions', result)
        self.assertIn('### Protected Functions', result)
        result = render([('func', False), ('var', False)])
        self.assertIn('### Public Functions', result)
        self.assertIn('### Public Attributes', result)
        # Enums and typedefs share the existing Types subgroup.
        self.assertNotIn('### ', render([('enum', False), ('typedef', False)]))

    def test_cells_and_overloads(self):
        templates = pathlib.Path(__file__).parents[1] / 'templates' / 'doxybook2'
        env = Environment(loader=FileSystemLoader(str(templates)),
                          trim_blocks=True, lstrip_blocks=True)
        macros = env.get_template('macros.md.jinja2').module
        self.assertEqual(macros.table_cell('a|b\nc'), 'a\\|b<br>c')
        self.assertEqual(macros.table_type('const char *'), 'const char \\*')
        child = dict(name='connect', kind='function', params=[dict(
            parsed_type=dict(parts=[dict(text='const '),
                                    dict(link_text_markdown='String'), dict(text=' &')]))])
        self.assertEqual(macros.member_name(child), 'connect(const String &)')
