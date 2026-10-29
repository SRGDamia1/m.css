"""Regression tests for templates consuming ParameterInfo objects."""

import unittest
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader

from doxygen import DefineMember, FunctionMember, ParameterInfo


class ParameterInfoTemplates(unittest.TestCase):
    def setUp(self):
        self.templates = Path(__file__).parents[1] / 'templates'

    def _environment(self, directory):
        return Environment(
            loader=FileSystemLoader(str(self.templates / directory)),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    @staticmethod
    def _define():
        define = DefineMember()
        define.id = 'read'
        define.kind = 'define'
        define.name = 'READ'
        define.initializer = 'value'
        define.has_details = True
        define.has_param_details = True
        parameter = ParameterInfo('value')
        parameter.description = 'Value to read.'
        parameter.description_markdown = 'Value to read.'
        define.params = [parameter]
        return define

    @staticmethod
    def _function():
        function = FunctionMember()
        function.id = 'parse'
        function.name = 'parse'
        function.templates = None
        return_value = ParameterInfo('0')
        return_value.description = 'Success.'
        return_value.description_markdown = 'Success.'
        exception = ParameterInfo('ParseError')
        exception.description = 'Input was invalid.'
        exception.description_markdown = 'Input was invalid.'
        function.return_values = [return_value]
        function.exceptions = [exception]
        return function

    def test_html_templates_render_parameter_info(self):
        compound = SimpleNamespace(url='', templates=None)
        for directory, suffix in (
            ('doxygen', '.html'),
            ('EnviroDIY', '.html.jinja2'),
        ):
            with self.subTest(directory=directory, template='define'):
                environment = self._environment(directory)
                define = self._define()
                details = environment.get_template(
                    'details-define' + suffix).render(define=define)
                entry = environment.get_template(
                    'entry-define' + suffix).render(
                        compound=compound, define=define)
                self.assertIn('READ', details)
                self.assertIn('value', details)
                self.assertIn('Value to read.', details)
                self.assertIn('READ', entry)
                self.assertIn('value', entry)

            with self.subTest(directory=directory, template='function'):
                rendered = environment.get_template(
                    'details-func' + suffix).render(
                        compound=compound, func=self._function())
                self.assertIn('0', rendered)
                self.assertIn('Success.', rendered)
                self.assertIn('ParseError', rendered)
                self.assertIn('Input was invalid.', rendered)

    def test_markdown_templates_render_parameter_info(self):
        environment = self._environment('doxybook2')

        define = self._define()
        rendered = environment.get_template(
            'member_details.md.jinja2').render(compound=define)
        self.assertIn('#define READ(value) value', rendered)

        rendered = environment.get_template(
            'nonclass_members_tables.md.jinja2').render(
                compound=SimpleNamespace(defines=[define]))
        self.assertIn('READ', rendered)
        self.assertIn('(value)', rendered)

        rendered = environment.get_template(
            'details.md.jinja2').render(compound=self._function())
        self.assertIn('**0** Success.', rendered)
        self.assertIn('**ParseError** Input was invalid.', rendered)


if __name__ == '__main__':
    unittest.main()
