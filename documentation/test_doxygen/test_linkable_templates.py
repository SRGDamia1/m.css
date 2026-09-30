import os
import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from doxygen import (
    AnchorLink,
    EnumMember,
    FunctionMember,
    ParameterInfo,
    ParsedLinkable,
    ReferenceLink,
    TextLink,
    TypedefMember,
    VariableMember,
    render_linkable_html,
    render_linkable_markdown,
)


class ParsedLinkableTemplateContract(unittest.TestCase):
    def test_renderers_preserve_linkable_parts(self):
        parsed = ParsedLinkable()
        reference = ReferenceLink()
        reference.url = 'class_foo{extension}#foo'
        reference.link_text = 'Foo'
        parsed.parts = [
            TextLink('const '),
            reference,
            TextLink(' *'),
            AnchorLink('deprecated'),
        ]

        self.assertEqual(
            render_linkable_html(parsed),
            'const <a href="class_foo.html#foo" class="m-doc">Foo</a>*<a name="deprecated"></a>',
        )
        self.assertEqual(
            render_linkable_markdown(parsed),
            'const [Foo](class_foo.md#foo)*<a id="deprecated"></a>',
        )

    def test_models_expose_parsed_and_rendered_type_fields(self):
        for model in (ParameterInfo(), EnumMember(), TypedefMember(), FunctionMember(), VariableMember()):
            self.assertIsInstance(model.parsed_type, ParsedLinkable)
            self.assertEqual(model.type_html, '')
            self.assertEqual(model.type_markdown, '')

        typedef = TypedefMember()
        self.assertIsInstance(typedef.parsed_args, ParsedLinkable)
        self.assertEqual(typedef.args_html, '')
        self.assertEqual(typedef.args_markdown, '')

    def test_markdown_template_uses_rendered_type_fields(self):
        root = os.path.join(os.path.dirname(__file__), '..', '..', 'templates', 'templates', 'doxybook2')
        env = Environment(loader=FileSystemLoader(root), trim_blocks=True, lstrip_blocks=True)
        template = env.from_string('{% import "macros.md.jinja2" as macros %}{{ macros.function_with_params(child) }}')

        child = FunctionMember()
        child.name = 'foo'
        child.parsed_type.parts = [TextLink('const '), TextLink('Foo')]
        child.type_markdown = render_linkable_markdown(child.parsed_type)
        param = ParameterInfo('value')
        param.parsed_type.parts = [TextLink('Bar')]
        param.type_markdown = render_linkable_markdown(param.parsed_type)
        child.params = [param]

        rendered = template.render(child=child)
        self.assertIn('const Foo', rendered)
        self.assertIn('Bar value', rendered)

    def test_templates_reference_rendered_fields(self):
        root = Path(os.path.join(os.path.dirname(__file__), '..', '..', 'templates', 'templates'))
        html_files = [
            root / 'EnviroDIY' / name for name in (
                'details-func.html.jinja2', 'entry-func.html.jinja2',
                'details-typedef.html.jinja2', 'entry-typedef.html.jinja2',
                'details-var.html.jinja2', 'entry-var.html.jinja2',
                'details-enum.html.jinja2', 'entry-enum.html.jinja2',
                'entry-class.html.jinja2', 'base-class-reference.html.jinja2',
            )
        ]
        for path in html_files:
            text = path.read_text()
            self.assertNotRegex(text, r'\b(?:func|var|typedef|enum|t|param)\.type(?:\s|[}\%])')

        markdown_files = [
            root / 'doxybook2' / name for name in (
                'macros.md.jinja2', 'member_details.md.jinja2',
                'class.md.jinja2', 'struct.md.jinja2',
            )
        ]
        for path in markdown_files:
            text = path.read_text()
            self.assertNotRegex(text, r'\b(?:param|child|compound)\.type(?:\s|[}\%])')

        self.assertIn('type_html', (root / 'EnviroDIY' / 'entry-func.html.jinja2').read_text())
        self.assertIn('type_markdown', (root / 'doxybook2' / 'macros.md.jinja2').read_text())
        self.assertIn('args_html', (root / 'EnviroDIY' / 'entry-typedef.html.jinja2').read_text())


if __name__ == '__main__':
    unittest.main()
