#!/usr/bin/env python3

#
#   This file is part of m.css.
#
#   Copyright © 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025
#             Vladimír Vondruš <mosra@centrum.cz>
#   Copyright © 2018 Ryohei Machida <machida_mn@complex.ist.hokudai.ac.jp>
#   Copyright © 2018 Arvid Gerstmann <dev@arvid-g.de>
#   Copyright © 2019, 2021 Cris Luengo <cris.l.luengo@gmail.com>
#   Copyright © 2020 Rémi Marche <remimarche@gmail.com>
#   Copyright © 2020 Yuri Edward <nicolas1.fraysse@epitech.eu>
#   Copyright © 2020 Sergei Izmailov <sergei.a.izmailov@gmail.com>
#   Copyright © 2020 Marin <marin.jurjevic@hotmail.com>
#   Copyright © 2021 Maxime Schmitt <maxime.schmitt91@gmail.com>
#   Copyright © 2021 Wojciech Jarosz <wkjarosz@users.noreply.github.com>
#   Copyright © 2022 crf8472 <crf8472@web.de>
#   Copyright © 2022 SRGDamia1 <sdamiano@stroudcenter.org>
#   Copyright © 2022 luz paz <luzpaz@pm.me>
#   Copyright © 2022 Mark Gillard <marzer_@hotmail.com>
#
#   Permission is hereby granted, free of charge, to any person obtaining a
#   copy of this software and associated documentation files (the "Software"),
#   to deal in the Software without restriction, including without limitation
#   the rights to use, copy, modify, merge, publish, distribute, sublicense,
#   and/or sell copies of the Software, and to permit persons to whom the
#   Software is furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included
#   in all copies or substantial portions of the Software.
#
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
#   THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#   FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#   DEALINGS IN THE SOFTWARE.
#

import xml.etree.ElementTree as ET
import argparse
import copy
import enum
import sys
import re
import html
import inspect
import os
import glob
import mimetypes
import shutil
import subprocess
import urllib.parse
import logging
import json
from types import MappingProxyType, SimpleNamespace as Empty
from typing import Tuple, Dict, Any, List

from importlib.machinery import SourceFileLoader
from jinja2 import Environment, FileSystemLoader
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, BashSessionLexer, ArduinoLexer, CppLexer, get_lexer_by_name, find_lexer_class_for_filename

from _search import CssClass, ResultFlag, ResultMap, Trie, Serializer, serialize_search_data, base85encode_search_data, search_filename, searchdata_filename, searchdata_filename_b85, searchdata_format_version

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), '../plugins'))
import dot2svg
import latex2svg
import latex2svgextra
import ansilexer


class JSONDictEncoder(json.JSONEncoder):
    def default(self, obj):
        return obj.__dict__

# from https://bugs.python.org/issue34858
class MappingProxyEncoder(json.JSONEncoder):
  def default(self, obj):
    if isinstance(obj, MappingProxyType):
      return obj.copy()
    # return json.JSONEncoder.default(self, obj)
    return JSONDictEncoder.default(self, obj)


class WrappedLineFormatter(HtmlFormatter):
    def wrap(self, source):
        return self._wrap_code(source)

    # generator: returns 0, html if it's not a source line; 1, line if it is
    def _wrap_code(self, source):
        _prefix = ''
        # _prefix = '<div class="fragment">'  # put code in a fragment block
        # yield 0, _prefix + "<pre><code>"
        yield 0, _prefix

        for count, _t in enumerate(source):
            i, t = _t
            if i == 1:
                # it's a highlighted line - add a div around it
                _row = '<div class="line">{}</div>'.format(
                    t
                )
                t = _row
            yield i, t

        # close open things
        _postfix = ''
        # _postfix = '</div>'
        # yield 0, "</code></pre>" + _postfix
        yield 0, _postfix


class EntryType(enum.Enum):
    # Order must match the search_type_map below; first value is reserved for
    # ResultFlag.ALIAS
    PAGE = 1
    NAMESPACE = 2
    GROUP = 3
    CLASS = 4
    STRUCT = 5
    UNION = 6
    TYPEDEF = 7
    DIR = 8
    FILE = 9
    FUNC = 10
    DEFINE = 11
    ENUM = 12
    ENUM_VALUE = 13
    VAR = 14


# Order must match the EntryType above
search_type_map = [
    (CssClass.SUCCESS, "page"),
    (CssClass.PRIMARY, "namespace"),
    (CssClass.SUCCESS, "group"),
    (CssClass.PRIMARY, "class"),
    (CssClass.PRIMARY, "struct"),
    (CssClass.PRIMARY, "union"),
    (CssClass.PRIMARY, "typedef"),
    (CssClass.WARNING, "dir"),
    (CssClass.WARNING, "file"),
    (CssClass.INFO, "func"),
    (CssClass.INFO, "define"),
    (CssClass.PRIMARY, "enum"),
    (CssClass.DEFAULT, "enum val"),
    (CssClass.DEFAULT, "var")
]

default_config = {
    'DOXYFILE': 'Doxyfile',

    'THEME_COLOR': '#22272e',
    'FAVICON': 'favicon-dark.png',
    'LINKS_NAVBAR1': [
        ("Pages", 'pages', []),
        ("Namespaces", 'namespaces', [])
    ],
    'LINKS_NAVBAR2': [
        ("Classes", 'annotated', []),
        ("Files", 'files', [])
    ],

    'STYLESHEETS': [
        'https://fonts.googleapis.com/css?family=Source+Sans+Pro:400,400i,600,600i%7CSource+Code+Pro:400,400i,600',
        '../css/m-dark+documentation.compiled.css'],
    'HTML_HEADER': None,
    'EXTRA_FILES': [],
    'PAGE_HEADER': None,
    'FINE_PRINT': '[default]',

    'CLASS_INDEX_EXPAND_LEVELS': 1,
    'FILE_INDEX_EXPAND_LEVELS': 1,
    'CLASS_INDEX_EXPAND_INNER': False,

    'M_MATH_CACHE_FILE': 'm.math.cache',
    'M_MATH_RENDER_AS_CODE': False,
    'M_CODE_FILTERS_PRE': {},
    'M_CODE_FILTERS_POST': {},

    'SEARCH_DISABLED': False,
    'SEARCH_DOWNLOAD_BINARY': False,
    'SEARCH_FILENAME_PREFIX': 'searchdata',
    'SEARCH_RESULT_ID_BYTES': 2,
    'SEARCH_FILE_OFFSET_BYTES': 3,
    'SEARCH_NAME_SIZE_BYTES': 1,
    'SEARCH_HELP':
"""<p class="m-noindent">Search for symbols, directories, files, pages or
topics. You can omit any prefix from the symbol or file path; adding a
<code>:</code> or <code>/</code> suffix lists all members of given symbol or
directory.</p>
<p class="m-noindent">Use <span class="m-label m-dim">&darr;</span>
/ <span class="m-label m-dim">&uarr;</span> to navigate through the list,
<span class="m-label m-dim">Enter</span> to go.
<span class="m-label m-dim">Tab</span> autocompletes common prefix, you can
copy a link to the result using <span class="m-label m-dim">⌘</span>
<span class="m-label m-dim">L</span> while <span class="m-label m-dim">⌘</span>
<span class="m-label m-dim">M</span> produces a Markdown link.</p>
""",
    'SEARCH_BASE_URL': None,
    'SEARCH_EXTERNAL_URL': None,

    'SHOW_UNDOCUMENTED': False,
    'VERSION_LABELS': False
}

xref_id_rx = re.compile(r"""(.*)_1(_[a-z-0-9]+|@)$""")
slugify_nonalnum_rx = re.compile(r"""[^\w\s-]""")
slugify_hyphens_rx = re.compile(r"""[-\s]+""")


class StateCompound:
    def __init__(self):
        self.id: str
        self.kind: str
        self.name: str
        self.url: str
        self.brief: str
        self.has_details: bool
        self.deprecated: str
        self.is_final: bool = None
        self.children: List[str]
        self.childrenClasses: List[str] # 'innerclass'
        self.childrenNamespaces: List[str] # 'innernamespace'
        self.childrenCompoundRefs: List[str] # 'derivedcompoundref'
        self.parent: str = None
        self.parentGroup: str = None

    def __str__(self):
        return str(self.__class__) + ": " + str(self.__dict__)

    def __repr__(self):
        return str(self.__class__) + ": " + str(self.__dict__)


class State:
    def __init__(self, config):
        self.basedir = ''
        self.compounds: Dict[str, StateCompound] = {}
        self.includes: Dict[str, str] = {}
        self.search: List[Any] = []
        self.examples: List[Any] = []
        self.doxyfile: Dict[str, Any] = {}
        self.config: Dict[str, Any] = config
        self.images: List[str] = []
        self.current = '' # current file being processed (for logging)
        # Current kind of compound being processed. Affects current_include
        # below (i.e., per-entry includes are parsed only for namespaces or
        # topics, because for classes they are consistent and don't need to be
        # repeated).
        self.current_kind = None
        # If this is None (or becomes None), it means the compound is spread
        # over multiple files and thus every entry needs its own specific
        # include definition
        self.current_include = None
        self.current_prefix = []
        self.current_compound_url = None
        self.current_definition_url_base = None
        self.parsing_toplevel_desc = False

    def __str__(self):
        return str(self.__class__) + ": " + str(self.__dict__)

    def __repr__(self):
        return str(self.__class__) + ": " + str(self.__dict__)


def slugify(text: str) -> str:
    # Maybe some Unicode normalization would be nice here?
    return slugify_hyphens_rx.sub('-', slugify_nonalnum_rx.sub('', text.lower()).strip())

def add_wbr(text: str) -> str:
    # Stuff contains HTML code, do not touch!
    if '<' in text: return text

    if '::' in text: # C++ names
        return text.replace('::', '::<wbr />')
    elif '_' in text: # VERY_LONG_UPPER_CASE macro names
        return text.replace('_', '_<wbr />')

    # These characters are quite common, so at least check that there is no
    # space (which may hint that the text is actually some human language):
    elif '/' in text and not ' ' in text: # URLs
        return text.replace('/', '/<wbr />')
    else:
        return text

def parse_ref(state: State, element: ET.Element, add_inline_css_class: str = None) -> str:
    id = element.attrib['refid']

    # this is a reference to a compound - ie, something with its own xml file
    if element.attrib['kindref'] == 'compound':
        # TODO Unlike below, where the filename is dropped if it matches the
        # current compound URL, here I don't really know what to do because
        # <a> with empty href="" gets treated as a non-link by browsers.
        url = id + '.html'
    # a reference to a member - ie, something inside another compound's xml file
    elif element.attrib['kindref'] == 'member':
        i = id.rindex('_1')
        url = id[:i] + '.html'
        # There's no point in including the filename itself if linking to an
        # anchor on the same page.
        if url == state.current_compound_url:
            url = ''
        url += '#' + id[i+2:]
    else: # pragma: no cover
        logging.critical("{}: unknown <ref> kind {}".format(state.current, element.attrib['kindref']))
        assert False

    if 'external' in element.attrib:
        for i in state.doxyfile['TAGFILES']:
            name, _, baseurl = i.partition('=')
            if os.path.basename(name) == os.path.basename(element.attrib['external']):
                url = os.path.join(baseurl, url)
                break
        else: # pragma: no cover
            logging.critical("{}: tagfile {} not specified in Doxyfile".format(state.current, element.attrib['external']))
            assert False
        class_ = 'm-doc-external'
    else:
        class_ = 'm-doc'
    if add_inline_css_class: # Overrides the default set above
        class_ = add_inline_css_class

    return '<a href="{}" class="{}">{}</a>'.format(url, class_, add_wbr(parse_inline_desc(state, element).strip()))

# Returns a shortened path if the prefix matches
def remove_path_prefix(path: str, prefix: str) -> str:
    common_path = os.path.commonprefix([path, prefix])
    return path[len(common_path):].lstrip(os.path.sep) if common_path else path

# Return the string that has the longest prefix stripped, as defined by Doxygen
# in src/util.cpp
def make_include_strip_from_path(path: str, prefixes: List[str]) -> str:
    strip_candidates = list(filter(bool, map(lambda x: remove_path_prefix(path, x), prefixes)))
    return min(strip_candidates, key=len) if strip_candidates else path

def make_include(state: State, file) -> Tuple[str, str]:
    if file in state.includes and state.compounds[state.includes[file]].has_details:
        return (html.escape('<{}>'.format(make_include_strip_from_path(file, state.doxyfile['STRIP_FROM_INC_PATH']) if state.doxyfile['STRIP_FROM_INC_PATH'] is not None else file)), state.compounds[state.includes[file]].url)
    return None

# Used only from a single place but put here to ensure it's kept consistent
# with make_include() above, in particular the checks
def make_class_include(state: State, file_id, name) -> Tuple[str, str]:
    # state.includes is a map from a filename to file ID, and since we already
    # have a file ID we don't need to use it. But if it's empty, it means
    # includes are disabled globally, in which case we shouldn't return
    # anything.
    if state.includes and state.compounds[file_id].has_details:
        return (html.escape('<{}>'.format(name)), state.compounds[file_id].url)
    return None

def parse_id_and_include(state: State, element: ET.Element) -> Tuple[str, str, str, Tuple[str, str], bool]:
    # Returns URL base (usually saved to state.current_definition_url_base and
    # used by extract_id_hash() later), base URL (with file extension), and the
    # actual ID
    id = element.attrib['id']
    i = id.rindex('_1')

    # Extract the corresponding include, if the current compound is a namespace
    # or a topic (group/module)
    include = None
    has_details = False
    if state.current_kind in ['namespace', 'group']:
        location_attribs = element.find('location').attrib
        file = location_attribs['declfile'] if 'declfile' in location_attribs else location_attribs['file']
        include = make_include(state, file)

        # If the include for current namespace is not yet set (empty string)
        # but also not already signalled to be non-unique using None, set it to
        # this value. Need to do it this way instead of using the location
        # information from the compound, because namespace location is
        # sometimes pointed to a *.cpp file, which Doxygen sees before *.h.
        if not state.current_include and state.current_include is not None:
            assert state.current_kind == 'namespace'
            state.current_include = file
            # parse_xml() fills compound.include from this later

        # If the include differs from current compound include, reset it to
        # None to signal that the compound doesn't have one unique include
        # file. This will get later picked up by parse_xml() which either adds
        # has_details to all compounds or wipes the compound-specific includes.
        elif state.current_include and state.current_include != file:
            state.current_include = None

    # Extract corresponding include also for class/struct/union "relateds", if
    # it's different from what the class has. This also forcibly enables
    # has_details (unlike the case above, where has_details will be enabled
    # only if all members don't have the same include) -- however if
    # SHOW_INCLUDE_FILES isn't enabled or the file is not documented, this
    # would generate useless empty detailed sections so in that case it's not
    # set.
    if state.current_kind in ['class', 'struct', 'union']:
        location_attribs = element.find('location').attrib
        file = location_attribs['declfile'] if 'declfile' in location_attribs else location_attribs['file']
        if state.current_include != file:
            include = make_include(state, file)
            has_details = include and state.doxyfile['SHOW_INCLUDE_FILES']

    return id[:i], id[:i] + '.html', id[i+2:], include, has_details

def extract_id_hash(state: State, element: ET.Element) -> str:
    # Can't use parse_id() here as sections with _1 in it have it verbatim
    # unescaped and mess up with rindex(). OTOH, can't use this approach in
    # parse_id() because for example enums can be present in both file and
    # namespace documentation, having the base_url either the file one or the
    # namespace one, depending on what's documented better. Ugh. See the
    # contents_section_underscore_one test for a verification.
    #
    # Can't use current compound URL base here, as definitions can have
    # different URL base (again an enum being present in both file and
    # namespace documentation). The state.current_definition_url_base usually
    # comes from parse_id()[0]. See the
    # contents_anchor_in_both_group_and_namespace test for a verification.
    id = element.attrib['id']
    assert id.startswith(state.current_definition_url_base), "ID `%s` does not start with `%s`" % (id, state.current_definition_url_base)
    return id[len(state.current_definition_url_base)+2:]

and_re_src = re.compile(r'([^\s])&amp;&amp;([^\s])')
and_re_dst = r'\1 &amp;&amp; \2'

def fix_type_spacing(type: str) -> str:
    return and_re_src.sub(and_re_dst, type
        .replace('&lt; ', '&lt;')
        .replace(' &gt;', '&gt;')
        .replace(' &amp;', '&amp;')
        .replace(' *', '*'))

def parse_type(state: State, type: ET.Element) -> str:
    # Constructors and typeless enums might not have it
    if type is None: return None
    out = html.escape(type.text) if type.text else ''

    i: ET.Element
    for i in type:
        if i.tag == 'ref':
            out += parse_ref(state, i)
        elif i.tag == 'anchor':
            # Anchor, used by <= 1.8.14 for deprecated/todo lists. Its base_url
            # is always equal to base_url of the page. In 1.8.15 the anchor is
            # in the description, making the anchor look extra awful:
            # https://github.com/doxygen/doxygen/pull/6587
            # TODO: this should get reverted and fixed properly so the
            # one-on-one case works as it should
            out += '<a name="{}"></a>'.format(extract_id_hash(state, i))
        else: # pragma: no cover
            logging.warning("{}: ignoring {} in <type>".format(state.current, i.tag))

        if i.tail: out += html.escape(i.tail)

    # Remove spacing inside <> and before & and *
    return fix_type_spacing(out)

def parse_desc_internal(state: State, element: ET.Element, immediate_parent: ET.Element = None, trim = True, add_css_class = None):
    logging.debug(
        f"    Parsing internal description of {element.tag} in file {state.current}"
    )
    out = Empty()
    out.section = None
    out.templates = {}
    out.params = {}
    out.return_value = None
    out.return_values = []
    out.exceptions = []
    out.add_css_class = None
    out.footer_navigation = False
    out.example_navigation = None
    out.search_keywords = []
    out.search_enum_values_as_keywords = False
    out.deprecated = None
    out.since = None

    # DOXYGEN <PARA> PATCHING 1/4
    #
    # In the optimistic case, when parsing the <para> element, the parsed
    # content is treated as single reasonable paragraph and the caller is told
    # to write both <p> and </p> enclosing tag.
    #
    # Unfortunately Doxygen puts some *block* elements inside a <para> element
    # instead of closing it before and opening it again after. That is making
    # me raging mad. Nested paragraphs are no way valid HTML and they are ugly
    # and problematic in all ways you can imagine, so it's needed to be
    # patched. See the long ranty comments below for more parts of the story.
    out.write_paragraph_start_tag = element.tag == 'para'
    out.write_paragraph_close_tag = element.tag == 'para'
    out.is_reasonable_paragraph = element.tag == 'para'

    out.parsed: str = ''
    if element.text:
        out.parsed = html.escape(element.text.strip() if trim else element.text)

        # There's some inline text at the start, *do not* add any CSS class to
        # the first child element
        add_css_class = None

    # Needed later for deciding whether we can strip the surrounding <p> from
    # the content
    paragraph_count = 0
    has_block_elements = False

    # So we are able to merge content of adjacent sections. Tuple of (tag,
    # kind), set only if there is no i.tail, reset in the next iteration.
    previous_section = None

    # So we can peek what the previous element was. Needed by Doxygen 1.9
    # code-after-blockquote discovery.
    previous_element = None

    # A CSS class to be added inline (not propagated outside of the paragraph)
    add_inline_css_class = None

    # Also, to make things even funnier, parameter and return value description
    # come from inside of some paragraph and can be nested also inside lists
    # and whatnot. This bubbles them up. Unfortunately they can be scattered
    # around, so also merging them together.
    def merge_parsed_subsections(parsed):
        if parsed.templates:
            out.templates.update(parsed.templates)
        if parsed.params:
            out.params.update(parsed.params)
        if parsed.return_value:
            if out.return_value:
                logging.warning("{}: superfluous @return section found, ignoring: {}".format(state.current, ''.join(i.itertext()).rstrip()))
            else:
                out.return_value = parsed.return_value
        if parsed.return_values:
            out.return_values += parsed.return_values
        if parsed.exceptions:
            out.exceptions += parsed.exceptions
        if parsed.since:
            out.since = parsed.since
        if parsed.deprecated:
            assert not out.since
            out.deprecated = parsed.deprecated

    i: ET.Element
    # The index gets only used in <programlisting> code vs inline detection, to
    # check if there are any elements in the block element after it. All uses
    # of it need to take into account the <zwj/> skipping in Doxygen 1.9
    # blockquotes below.
    for index, i in enumerate(element):
        logging.debug(
            f"      Parsing internal description of {i.tag} within {element.tag} in file {state.current}"
        )
        # As of 1.9.3 and https://github.com/doxygen/doxygen/pull/7422, a
        # stupid &zwj; is added at the front of every Markdown blockquote for
        # some silly reason, and then the Markdown is processed as a HTML,
        # resulting in <blockquote><para><zwj/>. Drop the <zwj/> from there, as
        # it's useless and messes up with our <para> patching logic.
        if index == 0 and i.tag == 'zwj' and element.tag == 'para' and immediate_parent is not None and immediate_parent.tag == 'blockquote':
            if i.tail:
                tail: str = html.escape(i.tail)
                if trim:
                    tail = tail.strip()
                out.parsed += tail
            continue

        # State used later
        code_block = None
        formula_block = None

        # A section was left open, but there's nothing to continue it, close
        # it. Expect that there was nothing after that would mess with us.
        # Don't reset it back to None just yet, as inline/block code
        # autodetection needs it.
        if previous_section and (i.tag != 'simplesect' or i.attrib['kind'] == 'return'):
            assert not out.write_paragraph_close_tag
            out.parsed = out.parsed.rstrip() + '</aside>'

        # Decide if a formula / code snippet is a block or not
        # <formula> can be both, depending on what's inside
        if i.tag == 'formula':
            if i.text.startswith('$') and i.text.endswith('$'):
                formula_block = False
            else:
                formula_block = True

        # <programlisting> is autodetected to be either block or inline
        elif i.tag == 'programlisting':
            # In a blockquote we need to not count the initial <zwj/> added by
            # Doxygen 1.9. Otherwise all code blocks alone in a blockquote
            # would be treated as inline.
            if element.tag == 'para' and immediate_parent is not None and immediate_parent.tag == 'blockquote':
                element_children_count = 0
                for listing_index, listing in enumerate(element):
                    if listing_index == 0 and listing.tag == 'zwj': continue
                    element_children_count += 1
            else:
                element_children_count = len([listing for listing in element])

            # If it seems to be a standalone code paragraph, don't wrap it
            # in <p> and use <pre>:
            if (
                # It's either alone in the paragraph, with no text or other
                # elements around, or
                ((not element.text or not element.text.strip()) and (not i.tail or not i.tail.strip()) and element_children_count == 1) or

                # is a code snippet, i.e. filename instead of just .ext
                # (Doxygen unfortunately doesn't put @snippet in its own
                # paragraph even if it's separated by blank lines. It does
                # so for @include and related, though.)
                ('filename' in i.attrib and not i.attrib['filename'].startswith('.')) or

                # or is
                #   - code right after a note/attention/... section
                #   - or in Doxygen 1.9 code right after a blockquote, which is
                #     no longer wrapped into its own <para>,
                # there's no text after and it's the last thing in the
                # paragraph (Doxygen ALSO doesn't separate end of a section
                # and begin of a code block by a paragraph even if there is
                # a blank line. But it does so for xrefitems such as @todo.
                # I don't even.)
                ((previous_section or (previous_element is not None and previous_element.tag == 'blockquote')) and (not i.tail or not i.tail.strip()) and index + 1 == element_children_count)
            ):
                code_block = True

            # Looks like inline code, but has multiple code lines, so it's
            # suspicious. Use code block, but warn.
            elif len([codeline for codeline in i]) > 1:
                code_block = True
                logging.warning("{}: inline code has multiple lines, fallback to a code block".format(state.current))

            # Otherwise wrap it in <p> and use <code>
            else:
                code_block = False

        # DOXYGEN <PARA> PATCHING 2/4
        #
        # Upon encountering a block element nested in <para>, we need to act.
        # If there was any content before, we close the paragraph. If there
        # wasn't, we tell the caller to not even open the paragraph. After
        # processing the following tag, there probably won't be any paragraph
        # open, so we also tell the caller that there's no need to close
        # anything (but it's not that simple, see for more patching at the end
        # of the cycle iteration).
        #
        # Those elements are:
        # - <heading>
        # - <blockquote>
        # - <hruler>
        # - <simplesect> (if not describing return type) and <xrefsect>
        # - <verbatim>, <preformatted> (those are the same thing!)
        # - <parblock> (a weird grouping thing that we abuse for <div>s)
        # - <variablelist>, <itemizedlist>, <orderedlist>
        # - <image>, <dot>, <dotfile>, <table>
        # - <mcss:div>
        # - <formula> (if block)
        # - <programlisting> (if block)
        # - <htmlonly> (if block, which is ATM always)
        #
        # <parameterlist> and <simplesect kind="return"> are extracted out of
        # the text flow, so these are removed from this check.
        #
        # In addition, there's special handling to achieve things like this:
        #   <ul>
        #     <li>A paragraph
        #       <ul>
        #         <li>A nested list item</li>
        #       </ul>
        #     </li>
        # I.e., not wrapping "A paragraph" in a <p>, but only if it's
        # immediately followed by another and it's the first paragraph in a
        # list item. We check that using the immediate_parent variable.
        if element.tag == 'para':
            end_previous_paragraph = False

            # Straightforward elements
            if i.tag in ['heading', 'blockquote', 'hruler', 'xrefsect', 'variablelist', 'verbatim', 'parblock', 'preformatted', 'itemizedlist', 'orderedlist', 'image', 'dot', 'dotfile', 'table', '{http://mcss.mosra.cz/doxygen/}div', 'htmlonly']:
                end_previous_paragraph = True

            # <simplesect> describing return type is cut out of text flow, so
            # it doesn't contribute
            elif i.tag == 'simplesect' and i.attrib['kind'] != 'return':
                end_previous_paragraph = True

            # <formula> can be both, depending on what's inside
            elif i.tag == 'formula':
                assert formula_block is not None
                end_previous_paragraph = formula_block

            # <programlisting> is autodetected to be either block or inline
            elif i.tag == 'programlisting':
                assert code_block is not None
                end_previous_paragraph = code_block

            if end_previous_paragraph:
                out.is_reasonable_paragraph = False
                out.parsed = out.parsed.rstrip()
                if not out.parsed:
                    out.write_paragraph_start_tag = False
                elif immediate_parent is not None and immediate_parent.tag == 'listitem' and i.tag in ['itemizedlist', 'orderedlist']:
                    out.write_paragraph_start_tag = False
                elif out.write_paragraph_close_tag:
                    out.parsed += '</p>'
                out.write_paragraph_close_tag = False

            # There might be *inline* elements that need to start a *new*
            # paragraph, on the other hand. OF COURSE DOXYGEN DOESN'T DO THAT
            # EITHER. There's a similar block of code that handles case with
            # non-empty i.tail() at the end of the loop iteration.
            if not out.write_paragraph_close_tag and (i.tag in ['linebreak', 'anchor', 'computeroutput', 'emphasis', 'bold', 'ref', 'ulink'] or (i.tag == 'formula' and not formula_block) or (i.tag == 'programlisting' and not code_block)):
                # Assume sanity -- we are *either* closing a paragraph because
                # a new block element appeared after inline stuff *or* opening
                # a paragraph because there's inline text after a block
                # element and that is mutually exclusive.
                assert not end_previous_paragraph
                out.parsed += '<p>'
                out.write_paragraph_close_tag = True

        # Block elements. Until Doxygen 1.10 it was at most <sect4>, 1.11 seems
        # to have up to 6: https://github.com/doxygen/doxygen/issues/11016
        if i.tag in ['sect1', 'sect2', 'sect3', 'sect4', 'sect5', 'sect6']:
            assert element.tag != 'para' # should be top-level block element
            has_block_elements = True

            parsed = parse_desc_internal(state, i)

            # Render as <section> in toplevel desc
            if state.parsing_toplevel_desc:
                assert parsed.section
                if parsed.templates or parsed.params or parsed.return_value or parsed.return_values or parsed.exceptions:
                    logging.warning("{}: unexpected @tparam / @param / @return / @retval / @exception found inside a @section, ignoring".format(state.current))

                # Top-level section has no ID or title
                if not out.section: out.section = ('', '', [])
                out.section = (out.section[0], out.section[1], out.section[2] + [parsed.section])
                out.parsed += '<section id="{}">{}</section>'.format(extract_id_hash(state, i), parsed.parsed)

            # Render directly the contents otherwise, propagate parsed stuff up
            else:
                merge_parsed_subsections(parsed)
                out.parsed += parsed.parsed

            if parsed.search_keywords:
                out.search_keywords += parsed.search_keywords

        elif i.tag == 'title':
            assert element.tag != 'para' # should be top-level block element
            has_block_elements = True

            # Top-level description
            if state.parsing_toplevel_desc:
                if element.tag == 'sect1':
                    tag = 'h2'
                elif element.tag == 'sect2':
                    tag = 'h3'
                elif element.tag == 'sect3':
                    tag = 'h4'
                elif element.tag == 'sect4':
                    tag = 'h5'
                elif element.tag == 'sect5':
                    tag = 'h6'
                elif element.tag == 'sect6':
                    tag = 'h6'
                    logging.warning("{}: more than five levels of sections in top level descriptions are not supported, stopping at <h6>".format(state.current))
                elif not element.tag == 'simplesect': # pragma: no cover
                    assert False

            # Function/enum/... descriptions are inside <h3> for function
            # header, which is inside <h2> for detailed definition section, so
            # it needs to be <h4> and below
            else:
                if element.tag == 'sect1':
                    tag = 'h4'
                elif element.tag == 'sect2':
                    tag = 'h5'
                elif element.tag == 'sect3':
                    tag = 'h6'
                elif element.tag in ['sect4', 'sect5', 'sect6']:
                    tag = 'h6'
                    logging.warning("{}: more than three levels of sections in member descriptions are not supported, stopping at <h6>".format(state.current))
                elif not element.tag == 'simplesect': # pragma: no cover
                    assert False

            # simplesect titles are handled directly inside simplesect
            if not element.tag == 'simplesect':
                id = extract_id_hash(state, element)
                title = html.escape(i.text)

                # Populate section info for top-level desc
                if state.parsing_toplevel_desc:
                    assert not out.section
                    out.section = (id, title, [])
                    # out.parsed += '<{0}><a href="#{1}">{2}</a></{0}>'.format(tag, id, title)
                    out.parsed += '<{0}>{2}</{0}>'.format(tag, id, title)

                # Otherwise add the ID directly to the heading
                else:
                    out.parsed += '<{0} id="{1}">{2}</{0}>'.format(tag, id, title)

        # Apparently, in 1.8.18, <heading> is used for Markdown headers only if
        # we run out of sect1-4 tags. Which also happens when there's a heading
        # with a ####### underline. In 1.11+ it doesn't produce a <heading>,
        # and instead just puts the #'s to the output verbatim. Which means we
        # can't warn for that. See test_contents.SectionsHeadings for repro
        # cases.
        elif i.tag == 'heading':
            assert element.tag == 'para' # is inside a paragraph :/
            has_block_elements = True

            # Do not print anything if there are no contents
            if not i.text:
                logging.warning("{}: a Markdown heading underline was apparently misparsed by Doxygen, prefix the headings with # instead".format(state.current))

            else:
                h_tag_level = int(i.attrib['level'])
                assert h_tag_level > 0

                # Top-level description can have 5 levels (first level used for
                # page title), so it needs to be <h2> and below
                if state.parsing_toplevel_desc:
                    h_tag_level += 1
                    if h_tag_level > 6:
                        h_tag_level = 6
                        logging.warning("{}: more than five levels of Markdown headings for top-level docs are not supported, stopping at <h6>".format(state.current))

                # Function/enum/... descriptions are inside <h3> for function
                # header, which is inside <h2> for detailed definition section,
                # so it needs to be <h4> and below
                else:
                    h_tag_level += 3
                    if h_tag_level > 6:
                        h_tag_level = 6
                        logging.warning("{}: more than three levels of Markdown headings in member descriptions are not supported, stopping at <h6>".format(state.current))

                out.parsed += '<h{0}>{1}</h{0}>'.format(h_tag_level, html.escape(i.text))

        elif i.tag == 'parblock':
            assert element.tag in ['para', '{http://mcss.mosra.cz/doxygen/}div']
            has_block_elements = True
            out.parsed += '<div{}>{}</div>'.format(
                ' class="{}"'.format(add_css_class) if add_css_class else '',
                parse_desc(state, i))

        elif i.tag == 'para':
            assert element.tag != 'para' # should be top-level block element
            paragraph_count += 1

            # DOXYGEN <PARA> PATCHING 3/4
            #
            # Parse contents of the paragraph, don't trim whitespace around
            # nested elements but trim it at the begin and end of the paragraph
            # itself. Also, some paragraphs are actually block content and we
            # might not want to write the start/closing tag.
            #
            # There's also the patching of nested lists that results in the
            # immediate_parent variable in the section 2/4 -- we pass the
            # parent only if this is the first paragraph inside it.
            parsed = parse_desc_internal(state, i,
                immediate_parent=element if paragraph_count == 1 and not has_block_elements else None,
                trim=False,
                add_css_class=add_css_class)
            parsed.parsed = parsed.parsed.strip()
            if not parsed.is_reasonable_paragraph:
                has_block_elements = True
            if parsed.parsed:
                if parsed.write_paragraph_start_tag:
                    # If there is some inline content at the beginning, assume
                    # the CSS class was meant to be added to the paragraph
                    # itself, not into a nested (block) element.
                    out.parsed += '<p{}>'.format(' class="{}"'.format(add_css_class) if add_css_class else '')
                out.parsed += parsed.parsed
                if parsed.write_paragraph_close_tag: out.parsed += '</p>'

            # Paragraphs can have nested parameter / return value / ...
            # descriptions, merge them to current state
            merge_parsed_subsections(parsed)

            # The same is (of course) with bubbling up the <mcss:class>
            # element. Reset the current value with the value coming from
            # inside -- it's either reset back to None or scheduled to be used
            # in the next iteration. In order to make this work, the resetting
            # code at the end of the loop iteration resets it to None only if
            # this is not a paragraph or the <mcss:class> element -- so we are
            # resetting here explicitly.
            add_css_class = parsed.add_css_class

            # Bubble up also footer / example navigation, search keywords,
            # deprecation flag, since badges
            if parsed.footer_navigation: out.footer_navigation = True
            if parsed.example_navigation: out.example_navigation = parsed.example_navigation
            out.search_keywords += parsed.search_keywords
            if parsed.search_enum_values_as_keywords: out.search_enum_values_as_keywords = True

            # Assert we didn't miss anything important
            assert not parsed.section

        elif i.tag == 'blockquote':
            assert element.tag in ['para', '{http://mcss.mosra.cz/doxygen/}div']
            has_block_elements = True
            out.parsed += '<blockquote>{}</blockquote>'.format(parse_desc(state, i))

        elif i.tag in ['itemizedlist', 'orderedlist']:
            assert element.tag in ['para', '{http://mcss.mosra.cz/doxygen/}div']
            has_block_elements = True
            tag = 'ul' if i.tag == 'itemizedlist' else 'ol'
            out.parsed += '<{}{}>'.format(tag,
                ' class="{}"'.format(add_css_class) if add_css_class else '')

            for li in i:
                assert li.tag == 'listitem'
                parsed = parse_desc_internal(state, li)
                out.parsed += '<li>{}</li>'.format(parsed.parsed)

                # Lists can have nested parameter / return value / ...
                # descriptions, bubble them up. THIS IS FUCKEN UNBELIEVABLE.
                merge_parsed_subsections(parsed)

                # Bubble up keywords as well
                if parsed.search_keywords:
                    out.search_keywords += parsed.search_keywords

            out.parsed += '</{}>'.format(tag)

        elif i.tag == 'table':
            assert element.tag in ['para', '{http://mcss.mosra.cz/doxygen/}div']
            has_block_elements = True
            out.parsed += '<table {}>'.format(
                'class="m-table ' + add_css_class  + '' if add_css_class else 'class="m-table m-fullwidth m-flat"')
            # out.parsed += '<table class="m-table{}">'.format(
            #     ' ' + add_css_class if add_css_class else '')
            thead_written = False
            inside_tbody = False

            row: ET.Element
            for row in i:
                if row.tag == 'caption':
                    out.parsed += '<caption>{}</caption>'.format(parse_inline_desc(state, row))

                if row.tag == 'row':
                    is_header_row = True
                    row_data = ''
                    for entry in row:
                        assert entry.tag == 'entry'
                        is_header = entry.attrib['thead'] == 'yes'
                        is_header_row = is_header_row and is_header
                        rowspan = ' rowspan="{}"'.format(entry.attrib['rowspan']) if 'rowspan' in entry.attrib else ''
                        colspan = ' colspan="{}"'.format(entry.attrib['colspan']) if 'colspan' in entry.attrib else ''
                        classes = ' class="{}"'.format(entry.attrib['class']) if 'class' in entry.attrib else ''
                        row_data += '<{0}{2}{3}{4}>{1}</{0}>'.format(
                            'th' if is_header else 'td',
                            parse_desc(state, entry),
                            rowspan, colspan, classes)

                    # Table head is opened upon encountering first header row
                    # and closed upon encountering first body row (in case it was
                    # ever opened). Encountering header row inside body again will
                    # not do anything special.
                    if is_header_row:
                        if not thead_written:
                            out.parsed += '<thead>'
                            thead_written = True
                    else:
                        if thead_written and not inside_tbody:
                            out.parsed += '</thead>'
                        if not inside_tbody:
                            out.parsed += '<tbody>'
                            inside_tbody = True

                    out.parsed += '<tr>{}</tr>'.format(row_data)

            if inside_tbody: out.parsed += '</tbody>'
            out.parsed += '</table>'

        elif i.tag == 'simplesect':
            assert element.tag == 'para' # is inside a paragraph :/

            # Return value is separated from the text flow
            if i.attrib['kind'] == 'return':
                if out.return_value:
                    logging.warning("{}: superfluous @return section found, ignoring: {}".format(state.current, ''.join(i.itertext()).rstrip()))
                else:
                    out.return_value = parse_desc(state, i)

            # Content of @since tags is put as-is into entry description /
            # details, if enabled.
            elif i.attrib['kind'] == 'since' and state.config['VERSION_LABELS']:
                since = parse_inline_desc(state, i).strip()
                assert since.startswith('<p>') and since.endswith('</p>')
                out.since = since[3:-4]

            else:
                has_block_elements = True

                # There was a section open, but it differs from this one, close
                # it
                if previous_section and ((i.attrib['kind'] != 'par' and previous_section != i.attrib['kind']) or (i.attrib['kind'] == 'par' and i.find('title').text)):
                    out.parsed = out.parsed.rstrip() + '</aside>'

                # Not continuing with a section from before, put a header in
                if not previous_section or (i.attrib['kind'] != 'par' and previous_section != i.attrib['kind']) or (i.attrib['kind'] == 'par' and i.find('title').text):
                    # TODO: make it possible to override the class using @m_class,
                    # document this and document behavior of @par

                    if i.attrib['kind'] == 'see':
                        title = 'See also'
                        css_class = 'm-default'
                    elif i.attrib['kind'] == 'note':
                        title = 'Note'
                        css_class = 'm-info'
                    elif i.attrib['kind'] == 'attention':
                        title = 'Attention'
                        css_class = 'm-warning'
                    elif i.attrib['kind'] == 'warning':
                        title = 'Warning'
                        css_class = 'm-danger'
                    elif i.attrib['kind'] == 'author':
                        title = 'Author'
                        css_class = 'm-default'
                    elif i.attrib['kind'] == 'authors':
                        title = 'Authors'
                        css_class = 'm-default'
                    elif i.attrib['kind'] == 'copyright':
                        title = 'Copyright'
                        css_class = 'm-default'
                    elif i.attrib['kind'] == 'version':
                        title = 'Version'
                        css_class = 'm-default'
                    elif i.attrib['kind'] == 'since':
                        title = 'Since'
                        css_class = 'm-default'
                    elif i.attrib['kind'] == 'date':
                        title = 'Date'
                        css_class = 'm-default'
                    elif i.attrib['kind'] == 'pre':
                        title = 'Precondition'
                        css_class = 'm-success'
                    elif i.attrib['kind'] == 'post':
                        title = 'Postcondition'
                        css_class = 'm-success'
                    elif i.attrib['kind'] == 'invariant':
                        title = 'Invariant'
                        css_class = 'm-success'
                    elif i.attrib['kind'] == 'remark':
                        title = 'Remark'
                        css_class = 'm-default'
                    elif i.attrib['kind'] == 'par':
                        title = html.escape(i.findtext('title', ''))
                        css_class = 'm-default'
                    elif i.attrib['kind'] == 'rcs':
                        title = html.escape(i.findtext('title', ''))
                        css_class = 'm-default'
                    else: # pragma: no cover
                        title = ''
                        css_class = ''
                        logging.warning("{}: ignoring {} kind of <simplesect>".format(state.current, i.attrib['kind']))

                    if add_css_class:
                        css_class = add_css_class
                        heading = 'h3'
                    else:
                        css_class = 'm-note ' + css_class
                        heading = 'h4'

                    if title:
                        out.parsed += '<aside class="{css_class}"><{heading}>{title}</{heading}>'.format(
                            css_class=css_class,
                            heading=heading,
                            title=title)
                    else:
                        out.parsed += '<aside class="{}">'.format(css_class)

                # Parse the section contents and bubble important stuff up
                parsed, search_keywords, search_enum_values_as_keywords = parse_desc_keywords(state, i)
                out.parsed += parsed
                if search_keywords:
                    out.search_keywords += search_keywords
                if search_enum_values_as_keywords:
                    out.search_enum_values_as_keywords = True

                # There's something after, close it
                if i.tail and i.tail.strip():
                    out.parsed += '</aside>'
                    previous_section = None

                # Otherwise put the responsibility on the next iteration, maybe
                # there are more paragraphs that should be merged
                else:
                    previous_section = i.attrib['kind']

        elif i.tag == 'xrefsect':
            assert element.tag == 'para' # is inside a paragraph :/
            has_block_elements = True

            # Not merging these, as every has usually a different ID each. (And
            # apparently Doxygen is able to merge them *but only if* they
            # describe some symbol, not on a page.)
            id = i.attrib['id']
            match = xref_id_rx.match(id)
            file = match.group(1)
            title = i.find('xreftitle').text
            if add_css_class:
                css_class = add_css_class
                heading = 'h3'
            else:
                heading = 'h4'
                css_class = 'm-note '
                # If we have version info from a previous Since badge, use it
                # instead of the title
                if file.startswith('deprecated'):
                    css_class += 'm-danger'
                    if out.since:
                        out.deprecated = out.since
                        title = out.since.capitalize()
                        out.since = None
                    else:
                        out.deprecated = 'deprecated'
                        title = 'Deprecated'
                elif file.startswith('bug'):
                    css_class += 'm-danger'
                elif file.startswith('todo'):
                    css_class += 'm-dim'
                else:
                    css_class += 'm-default'
            out.parsed += '<aside class="{css_class}"><{heading}><a href="{file}.html#{anchor}" class="m-doc">{title}</a></{heading}>{description}</aside>'.format(
                css_class=css_class,
                heading=heading,
                file=file,
                anchor=match.group(2),
                title=title,
                description=parse_desc(state, i.find('xrefdescription')))

        elif i.tag == 'parameterlist':
            assert element.tag == 'para' # is inside a paragraph :/
            has_block_elements = True

            for param in i:
                # This is an overcomplicated shit, so check sanity
                # http://www.stack.nl/~dimitri/doxygen/manual/commands.html#cmdparam
                assert param.tag == 'parameteritem'
                assert len(param.findall('parameternamelist')) == 1

                # This is only for PHP, ignore for now
                param_names = param.find('parameternamelist')
                assert param_names.find('parametertype') is None

                description = parse_desc(state, param.find('parameterdescription'))

                # Gather all names (so e.g. `@param x, y, z` is turned into
                # three params sharing the same description)
                for name in param_names.findall('parametername'):
                    if i.attrib['kind'] == 'param':
                        out.params[name.text] = (description, name.attrib['direction'] if 'direction' in name.attrib else '')
                    elif i.attrib['kind'] == 'retval':
                        out.return_values += [(name.text, description)]
                    elif i.attrib['kind'] == 'exception':
                        ref = name.find('ref')
                        if (ref != None):
                            out.exceptions += [(parse_ref(state, ref), description)]
                        else:
                            out.exceptions += [(name.text, description)]
                    else:
                        assert i.attrib['kind'] == 'templateparam'
                        out.templates[name.text] = description

        elif i.tag == 'variablelist':
            assert element.tag in ['para', '{http://mcss.mosra.cz/doxygen/}div']
            has_block_elements = True
            # Usually, <variablelist> is used to format todo lists and other
            # xrefitems (without being explicitly marked as such, of course),
            # in which case the styling is provided by the m-doc CSS class. But
            # if the user explicitly provided a CSS class using @m_class, then
            # it was probably literal <dl> directly in the markup, used for
            # example for a footnote list. In that case use the provided class
            # instead of m-doc.
            out.parsed += '<dl class="{}">'.format(add_css_class if add_css_class else 'm-doc')

            for var in i:
                if var.tag == 'varlistentry':
                    out.parsed += '<dt>{}</dt>'.format(parse_type(state, var.find('term')).strip())
                else:
                    assert var.tag == 'listitem'
                    out.parsed += '<dd>{}</dd>'.format(parse_desc(state, var))

            out.parsed += '</dl>'

        elif i.tag in ['verbatim', 'preformatted']:
            assert element.tag in ['para', '{http://mcss.mosra.cz/doxygen/}div']
            has_block_elements = True
            out.parsed += '<pre>{}</pre>'.format(html.escape(i.text or ''))

        elif i.tag == 'image':
            assert element.tag in ['para', '{http://mcss.mosra.cz/doxygen/}div', 'ulink']
            has_block_elements = True

            name = i.attrib['name']
            if i.attrib['type'] == 'html':
                path = os.path.join(state.basedir, state.doxyfile['OUTPUT_DIRECTORY'], state.doxyfile['XML_OUTPUT'], name)
                if os.path.exists(path):
                    state.images += [path]
                elif name.startswith('http://') or name.startswith('https://'):
                    pass # don't need to warn about missing image links
                else:
                    logging.warning("{}: image {} was not found in XML_OUTPUT".format(state.current, name))

                sizespec = ''
                if 'width' in i.attrib:
                    sizespec = ' style="width: {};"'.format(i.attrib['width'])
                elif 'height' in i.attrib:
                    sizespec = ' style="height: {};"'.format(i.attrib['height'])

                # The alt text can apparently be specified only with the HTML
                # <img> tag, not with @image. It's also present only since
                # 1.9.1(?).
                # TODO Doxygen seems to be double-escaping this, which
                #   ultimately means we cannot escape this ourselves as it'd be
                #   wrong. See test_contents.HtmlEscape for a repro case.
                alt = i.attrib.get('alt', 'Image')

                caption = i.text
                if caption:
                    out.parsed += '<figure class="m-figure{}"><img src="{}" alt="{}"{} /><figcaption>{}</figcaption></figure>'.format(
                        ' ' + add_css_class if add_css_class else '',
                        name, alt, sizespec, html.escape(caption))
                else:
                    out.parsed += '<img class="m-image{}" src="{}" alt="{}"{} />'.format(
                        ' ' + add_css_class if add_css_class else '', name, alt, sizespec)

        elif i.tag in ['dot', 'dotfile']:
            assert element.tag in ['para', '{http://mcss.mosra.cz/doxygen/}div']
            has_block_elements = True

            # Why the heck can't it just read the file and paste it into the
            # XML?!
            caption = None
            if i.tag == 'dotfile':
                if 'name' in i.attrib:
                    # Since 1.9.3, the file is copied to the XML output
                    # directory and name contains its relative path. Before
                    # that, the name was absolute, os.path.join() should do the
                    # right thing in both cases.
                    path = os.path.join(state.basedir, state.doxyfile['OUTPUT_DIRECTORY'], state.doxyfile['XML_OUTPUT'], i.attrib['name'])
                    with open(path, 'r') as f:
                        source = f.read()
                # Since 1.8.16 the whole <dotfile> tag is dropped if the file
                # doesn't exist. Such a great solution that it's unfathomable.
                # FFS.
                else:
                    logging.warning("{}: file passed to @dotfile was not found, rendering an empty graph".format(state.current))
                    source = 'digraph "" {}'
                caption = i.text
            else:
                source = i.text
                if 'caption' in i.attrib: caption = i.attrib['caption']

            size = None
            if 'width' in i.attrib:
                size = 'width: {};'.format(i.attrib['width'])
            elif 'height' in i.attrib:
                size = 'height: {};'.format(i.attrib['height'])

            if caption:
                out.parsed += '<figure class="m-figure">{}<figcaption>{}</figcaption></figure>'.format(dot2svg.dot2svg(
                    source, size=size,
                    attribs=' class="m-graph{}"'.format(' ' + add_css_class if add_css_class else '')),
                    caption)
            else:
                out.parsed += '<div class="m-graph{}">{}</div>'.format(
                    ' ' + add_css_class if add_css_class else '', dot2svg.dot2svg(source, size))

        elif i.tag == 'hruler':
            assert element.tag == 'para' # is inside a paragraph :/

            has_block_elements = True
            out.parsed += '<hr/>'

        elif i.tag == 'htmlonly':
            # The @htmlonly command has a block version, which is able to get
            # rid of the wrapping paragraph. But @htmlonly is not exposed to
            # XML because of https://github.com/doxygen/doxygen/pull/381. Only
            # @htmlinclude is exposed in XML and that one is always wrapped in
            # a paragraph.
            assert element.tag in ['para', '{http://mcss.mosra.cz/doxygen/}div']
            if i.text: out.parsed += i.text

        # Internal docs, parse only if these are enabled
        elif i.tag == 'internal':
            if state.doxyfile['INTERNAL_DOCS']:
                parsed = parse_desc_internal(state, i)
                merge_parsed_subsections(parsed)
                out.parsed += parsed.parsed

        # Custom <div> with CSS classes (for making dim notes etc)
        elif i.tag == '{http://mcss.mosra.cz/doxygen/}div':
            has_block_elements = True

            out.parsed += '<div class="{}">{}</div>'.format(i.attrib['{http://mcss.mosra.cz/doxygen/}class'], parse_inline_desc(state, i).strip())

        # Adding a custom CSS class to the immediately following block/inline
        # element
        elif i.tag == '{http://mcss.mosra.cz/doxygen/}class':
            # Doxygen may put one or more spaces before, depending on the
            # version. Replace them with just one to have consistent output
            # across all versions. Have to keep at least one as it's often
            # intentional, block elements such as <mcss:div> have both the
            # leading and trailing spaces stripped always. Sane is done for
            # <mcss:span> below.
            if out.parsed.endswith(' '):
                out.parsed = out.parsed.rstrip() + ' '

            # Bubble up in case we are alone in a paragraph, as that's meant to
            # affect the next paragraph content.
            if len([listing for listing in element]) == 1:
                out.add_css_class = i.attrib['{http://mcss.mosra.cz/doxygen/}class']

            # Otherwise this is meant to only affect inline elements in this
            # paragraph:
            else:
                add_inline_css_class = i.attrib['{http://mcss.mosra.cz/doxygen/}class']

        # Enabling footer navigation in a page
        elif i.tag == '{http://mcss.mosra.cz/doxygen/}footernavigation':
            out.footer_navigation = True

        # Enabling navigation for an example
        elif i.tag == '{http://mcss.mosra.cz/doxygen/}examplenavigation':
            out.example_navigation = (i.attrib['{http://mcss.mosra.cz/doxygen/}page'],
                                      i.attrib['{http://mcss.mosra.cz/doxygen/}prefix'])

        # Search-related stuff
        elif i.tag == '{http://mcss.mosra.cz/doxygen/}search':
            # Space-separated keyword list
            if '{http://mcss.mosra.cz/doxygen/}keywords' in i.attrib:
                out.search_keywords += [(keyword, '', 0) for keyword in i.attrib['{http://mcss.mosra.cz/doxygen/}keywords'].split(' ')]

            # Keyword with custom result title
            elif '{http://mcss.mosra.cz/doxygen/}keyword' in i.attrib:
                out.search_keywords += [(
                    i.attrib['{http://mcss.mosra.cz/doxygen/}keyword'],
                    i.attrib['{http://mcss.mosra.cz/doxygen/}title'],
                    int(i.attrib['{http://mcss.mosra.cz/doxygen/}suffix-length'] or '0'))]

            # Add values of this enum as search keywords
            elif '{http://mcss.mosra.cz/doxygen/}enum-values-as-keywords' in i.attrib:
                out.search_enum_values_as_keywords = True

            # Nothing else at the moment
            else:
                assert False  # pragma: no cover

        # Either block or inline
        elif i.tag == 'programlisting':
            assert element.tag in ['para', '{http://mcss.mosra.cz/doxygen/}div', '{http://mcss.mosra.cz/doxygen/}span']

            # We should have decided about block/inline above
            assert code_block is not None

            # Doxygen doesn't add a space before <programlisting> if it's
            # inline, add it manually in case there should be a space before
            # it. However, it does add a space after it always so we don't need
            # to.
            #
            # There doesn't need to be a space if it's a start of a tag, if
            # there's already one, if there's an opening brace before or if
            # <para> patching started a new paragraph right before.
            if not code_block:
                if out.parsed and not out.parsed[-1].isspace() and not out.parsed[-1] in '([{' and not out.parsed.endswith('<p>'):
                    out.parsed += ' '

            # Hammer unhighlighted code out of the block
            # TODO: preserve links
            code = ''
            codeline: ET.Element
            for codeline in i:
                assert codeline.tag == 'codeline'

                tag: ET.Element
                for tag in codeline:
                    assert tag.tag == 'highlight'
                    if tag.text: code += tag.text

                    token: ET.Element
                    for token in tag:
                        if token.tag == 'sp':
                            if 'value' in token.attrib:
                                code += chr(int(token.attrib['value']))
                            else:
                                code += ' '
                        elif token.tag == 'ref':
                            # Ignoring <ref> until a robust solution is found
                            # (i.e., also ignoring false positives)
                            code += token.text
                        else: # pragma: no cover
                            logging.warning("{}: unknown {} in a code block ".format(state.current, token.tag))

                        if token.tail: code += token.tail

                    if tag.tail: code += tag.tail

                code += '\n'

            # Strip whitespace around if inline code, strip only trailing
            # whitespace if a block
            if not code_block: code = code.strip()

            if not 'filename' in i.attrib:
                logging.warning("{}: no filename attribute in <programlisting>, assuming C++".format(state.current))
                filename = 'file.cpp'
            else:
                filename = i.attrib['filename']

            # Empty code block with a full filename -- probably a @skip /
            # @skipline / ... that didn't match anything. Be nice and warn,
            # because Doxygen doesn't.
            if not filename.startswith('.') and not code.strip():
                logging.warning("{}: @include / @snippet / @skip[line] produced an empty code block, probably a wrong match expression?".format(state.current))

            # Custom mapping of filenames to languages
            mapping = [('.h', 'c++'),
                       ('.h.cmake', 'c++'),
                       # Pygments knows only .vert, .frag, .geo
                       ('.glsl', 'glsl'),
                       ('.conf', 'ini'),
                       ('.conf.cmake', 'ini'),
                       ('.xml-jinja', 'xml+jinja'),
                       ('.html-jinja', 'html+jinja'),
                       ('.jinja', 'jinja'),
                       ('.ansi', ansilexer.AnsiLexer)]
            for key, v in mapping:
                if not filename.endswith(key): continue

                if isinstance(v, str):
                    lexer = get_lexer_by_name(v)
                else:
                    lexer = v()
                break

            # Otherwise try to find lexer by filename
            else:
                # Put some bogus prefix to the filename in case it is just
                # `.ext`
                lexer = find_lexer_class_for_filename("code" + filename)
                # warn if we cannot find a lexer and the language is anything other than 'unparsed'
                if not lexer:
                    if filename != ".unparsed":
                        logging.warning(
                            "{}: unrecognized language of {} in <programlisting>, highlighting disabled".format(
                                state.current, filename
                            )
                        )
                    lexer = TextLexer()
                else:
                    lexer = lexer()

            # Style console sessions differently
            if (isinstance(lexer, BashSessionLexer) or
                isinstance(lexer, ansilexer.AnsiLexer)):
                class_ = 'm-console'
            elif (isinstance(lexer, CppLexer) or
                isinstance(lexer, ArduinoLexer)):
                class_ = 'm-code-arduino'
            else:
                class_ = 'm-code-pygments-default'

            logging.debug(f"Formatting code for {filename} which {'is' if code_block else 'is not'} a code block with pygments lexer {lexer} using style class {class_}")

            if isinstance(lexer, ansilexer.AnsiLexer):
                formatter = ansilexer.HtmlAnsiFormatter(nowrap=True)
            else:
                formatter = WrappedLineFormatter(
                    nowrap=False,
                    wrapcode=True,
                    linenos="inline",
                    lineanchors="l",
                    anchorlinenos=False,
                )

            # Apply a global pre filter, if any
            filter = state.config['M_CODE_FILTERS_PRE'].get(lexer.name)
            if filter: code = filter(code)

            highlighted = highlight(code, lexer, formatter).rstrip().replace('\n</div><div', '</div>\n<div')

            # Pygments < 2.14 leave useless empty spans in the output. Filter
            # them out to have the markup consistent across versions for easier
            # testing.
            # TODO same is in m.code, remove once support for < 2.14 is dropped
            highlighted = (highlighted
                .replace('<span class="w"></span>', '')
                .replace('<span class="cp"></span>', ''))
            # Strip whitespace around if inline code, strip only trailing
            # whitespace if a block
            if not code_block: highlighted = highlighted.lstrip()

            # Apply a global post filter, if any
            filter = state.config['M_CODE_FILTERS_POST'].get(lexer.name)
            if filter: highlighted = filter(highlighted)

            out.parsed += '<{0} class="{1}{2}">{3}</{0}>'.format(
                # 'pre' if code_block else 'code',
                'div' if code_block else 'code',
                class_,
                ' ' + add_css_class if code_block and add_css_class else '',
                highlighted)

        # Either block or inline
        elif i.tag == 'formula':
            assert element.tag in ['para', '{http://mcss.mosra.cz/doxygen/}div']

            logging.debug("{}: rendering math: {}".format(state.current, i.text))

            # We should have decided about block/inline above
            assert formula_block is not None

            # Fallback rendering as code requested
            if state.config['M_MATH_RENDER_AS_CODE']:
                logging.debug("{}: rendering formula as code: {}".format(state.current, i.text))
                out.parsed += '<{0} class="m-code m-math{1}{2}">{3}</{0}>'.format(
                    'pre' if formula_block else 'code',
                    ' ' + add_css_class if formula_block and add_css_class else '',
                    # TODO try w/ this removed
                    ' ' + add_inline_css_class if not formula_block and add_inline_css_class else '',
                    i.text)
            elif state.doxyfile['USE_MATHJAX']:
                logging.debug("{}: leaving formula as un-formatted code for MathJax: {}".format(state.current, i.text))
                out.parsed += '<{0} class="m-code m-math{1}{2}">{3}</{0}>'.format(
                    'p',
                    ' ' + add_css_class if formula_block and add_css_class else '',
                    # TODO try w/ this removed
                    ' ' + add_inline_css_class if not formula_block and add_inline_css_class else '',
                    i.text)
            else:
                logging.debug("{}: converting math latex to svg: {}".format(state.current, i.text))
                # Assume that Doxygen wrapped the formula properly to
                # distinguish between inline, block or special environment
                depth, svg = latex2svgextra.fetch_cached_or_render('{}'.format(i.text))

                if formula_block:
                    has_block_elements = True
                    out.parsed += '<div class="m-math{}">{}</div>'.format(
                        ' ' + add_css_class if add_css_class else '',
                        latex2svgextra.patch(i.text, svg, None, ''))
                else:
                    # CSS classes and styling for proper vertical alignment.
                    # Depth is relative to font size, describes how below the
                    # line the text is. Scaling it back to 12pt font, scaled by
                    # 125% as set above in the config.
                    attribs = ' class="m-math{}"'.format(' ' + add_inline_css_class if add_inline_css_class else '')
                    out.parsed += latex2svgextra.patch(i.text, svg, depth, attribs)

        # Inline elements
        elif i.tag == 'linebreak':
            # Strip all whitespace before the linebreak, as it is of no use
            out.parsed = out.parsed.rstrip() + '<br />'

        elif i.tag == 'anchor':
            # Doxygen doesn't prefix HTML <a name=""> anchors the same way as
            # for @anchor (WHO WOULD HAVE THOUGHT, RIGHT), it just fully omits
            # the prefix. So allow that -- thus we can't just extract_id_hash()
            id = i.attrib['id']
            if id[:2] == '_1':
                id = id[2:]
            else:
                assert id.startswith(state.current_definition_url_base), "ID `%s` does not start with `%s`" % (id, state.current_definition_url_base)
                id = id[len(state.current_definition_url_base)+2:]
            out.parsed += '<a name="{}"></a>'.format(id)

        elif i.tag == 'computeroutput':
            content = parse_inline_desc(state, i).strip()
            if content: out.parsed += '<code>{}</code>'.format(content)

        elif i.tag in ['emphasis', 'bold', 'small', 'superscript', 'subscript', 'strike', 's', 'del']:
            mapping = {'emphasis': 'em',
                       'bold': 'strong',
                       'small': 'small',
                       'superscript': 'sup',
                       'subscript': 'sub',
                       'strike': 's',
                       's': 's',
                       'del': 's'}

            content = parse_inline_desc(state, i).strip()
            if content: out.parsed += '<{0}{1}>{2}</{0}>'.format(
                mapping[i.tag],
                ' class="{}"'.format(add_inline_css_class) if add_inline_css_class else '',
                content)

        elif i.tag == 'ref':
            out.parsed += parse_ref(state, i, add_inline_css_class)

        elif i.tag == 'ulink':
            out.parsed += '<a href="{}"{}>{}</a>'.format(
                html.escape(i.attrib['url']),
                ' class="{}"'.format(add_inline_css_class) if add_inline_css_class else '',
                add_wbr(parse_inline_desc(state, i).strip()))

        # <span> with custom CSS classes. This is (ab)used by the
        # M_SHOW_UNDOCUMENTED option to make things appear to be documented
        # in _document_all_stuff(). In that case the class attribute is not
        # present.
        elif i.tag == '{http://mcss.mosra.cz/doxygen/}span':
            # Doxygen may put one or more spaces before, depending on the
            # version. Replace them with just one to have consistent output
            # across all versions. Have to keep at least one as it's often
            # intentional, block elements such as <mcss:div> have both the
            # leading and trailing spaces stripped always. Sane is done for
            # <mcss:class> above.
            if out.parsed.endswith(' '):
                out.parsed = out.parsed.rstrip() + ' '

            content = parse_inline_desc(state, i).strip()
            if '{http://mcss.mosra.cz/doxygen/}class' in i.attrib:
                out.parsed += '<span class="{}">{}</span>'.format(i.attrib['{http://mcss.mosra.cz/doxygen/}class'], content)
            else:
                out.parsed += '<span>{}</span>'.format(content)

        # I'm hijacking the inner page to create page heirarchy without adding text to the pages
        # When the @subpage command is used on a page, it inserts a link on the original page
        # The @ingroup command doesn't work properly for pages parsed by m.css.
        # So I'm adding an xml-only tag to the page for the m.css metadata reader to grab
        # to get hierarchy without text
        elif i.tag=='innerpage':
            pass

        else:
            # Most of these are the same as HTML entities, but not all
            mapping = {'nonbreakablespace': 'nbsp',
                       'iexcl': 'iexcl',
                       'cent': 'cent',
                       'pound': 'pound',
                       'curren': 'curren',
                       'yen': 'yen',
                       'brvbar': 'brvbar',
                       'sect': 'sect',
                       'umlaut': 'uml',
                       'copy': 'copy',
                       'ordf': 'ordf',
                       'laquo': 'laquo',
                       'not': 'not',
                       'shy': 'shy',
                       'registered': 'reg',
                       'macr': 'macr',
                       'deg': 'deg',
                       'plusmn': 'plusmn',
                       'sup2': 'sup2',
                       'sup3': 'sup3',
                       'acute': 'acute',
                       'micro': 'micro',
                       'para': 'para',
                       'middot': 'middot',
                       'cedil': 'cedil',
                       'sup1': 'sup1',
                       'ordm': 'ordm',
                       'raquo': 'raquo',
                       'frac14': 'frac14',
                       'frac12': 'frac12',
                       'frac34': 'frac34',
                       'iquest': 'iquest',
                       'Agrave': 'Agrave',
                       'Aacute': 'Aacute',
                       'Acirc': 'Acirc',
                       'Atilde': 'Atilde',
                       'Aumlaut': 'Auml',
                       'Aring': 'Aring',
                       'AElig': 'AElig',
                       'Ccedil': 'Ccedil',
                       'Egrave': 'Egrave',
                       'Eacute': 'Eacute',
                       'Ecirc': 'Ecirc',
                       'Eumlaut': 'Euml',
                       'Igrave': 'Igrave',
                       'Iacute': 'Iacute',
                       'Icirc': 'Icirc',
                       'Iumlaut': 'Iuml',
                       'ETH': 'ETH',
                       'Ntilde': 'Ntilde',
                       'Ograve': 'Ograve',
                       'Oacute': 'Oacute',
                       'Ocirc': 'Ocirc',
                       'Otilde': 'Otilde',
                       'Oumlaut': 'Ouml',
                       'times': 'times',
                       'Oslash': 'Oslash',
                       'Ugrave': 'Ugrave',
                       'Uacute': 'Uacute',
                       'Ucirc': 'Ucirc',
                       'Uumlaut': 'Uuml',
                       'Yacute': 'Yacute',
                       'THORN': 'THORN',
                       'szlig': 'szlig',
                       'agrave': 'agrave',
                       'aacute': 'aacute',
                       'acirc': 'acirc',
                       'atilde': 'atilde',
                       'aumlaut': 'auml',
                       'aring': 'aring',
                       'aelig': 'aelig',
                       'ccedil': 'ccedil',
                       'egrave': 'egrave',
                       'eacute': 'eacute',
                       'ecirc': 'ecirc',
                       'eumlaut': 'euml',
                       'igrave': 'igrave',
                       'iacute': 'iacute',
                       'icirc': 'icirc',
                       'iumlaut': 'iuml',
                       'eth': 'eth',
                       'ntilde': 'ntilde',
                       'ograve': 'ograve',
                       'oacute': 'oacute',
                       'ocirc': 'ocirc',
                       'otilde': 'otilde',
                       'oumlaut': 'ouml',
                       'divide': 'divide',
                       'oslash': 'oslash',
                       'ugrave': 'ugrave',
                       'uacute': 'uacute',
                       'ucirc': 'ucirc',
                       'uumlaut': 'uuml',
                       'yacute': 'yacute',
                       'thorn': 'thorn',
                       'yumlaut': 'yuml',
                       'fnof': 'fnof',
                       'Alpha': 'Alpha',
                       'Beta': 'Beta',
                       'Gamma': 'Gamma',
                       'Delta': 'Delta',
                       'Epsilon': 'Epsilon',
                       'Zeta': 'Zeta',
                       'Eta': 'Eta',
                       'Theta': 'Theta',
                       'Iota': 'Iota',
                       'Kappa': 'Kappa',
                       'Lambda': 'Lambda',
                       'Mu': 'Mu',
                       'Nu': 'Nu',
                       'Xi': 'Xi',
                       'Omicron': 'Omicron',
                       'Pi': 'Pi',
                       'Rho': 'Rho',
                       'Sigma': 'Sigma',
                       'Tau': 'Tau',
                       'Upsilon': 'Upsilon',
                       'Phi': 'Phi',
                       'Chi': 'Chi',
                       'Psi': 'Psi',
                       'Omega': 'Omega',
                       'alpha': 'alpha',
                       'beta': 'beta',
                       'gamma': 'gamma',
                       'delta': 'delta',
                       'epsilon': 'epsilon',
                       'zeta': 'zeta',
                       'eta': 'eta',
                       'theta': 'theta',
                       'iota': 'iota',
                       'kappa': 'kappa',
                       'lambda': 'lambda',
                       'mu': 'mu',
                       'nu': 'nu',
                       'xi': 'xi',
                       'omicron': 'omicron',
                       'pi': 'pi',
                       'rho': 'rho',
                       'sigmaf': 'sigmaf',
                       'sigma': 'sigma',
                       'tau': 'tau',
                       'upsilon': 'upsilon',
                       'phi': 'phi',
                       'chi': 'chi',
                       'psi': 'psi',
                       'omega': 'omega',
                       'thetasym': 'thetasym',
                       'upsih': 'upsih',
                       'piv': 'piv',
                       'bull': 'bull',
                       'hellip': 'hellip',
                       'prime': 'prime',
                       'Prime': 'Prime',
                       'oline': 'oline',
                       'frasl': 'frasl',
                       'weierp': 'weierp',
                       'imaginary': 'image',
                       'real': 'real',
                       'trademark': 'trade',
                       'alefsym': 'alefsym',
                       'larr': 'larr',
                       'uarr': 'uarr',
                       'rarr': 'rarr',
                       'darr': 'darr',
                       'harr': 'harr',
                       'crarr': 'crarr',
                       'lArr': 'lArr',
                       'uArr': 'uArr',
                       'rArr': 'rArr',
                       'dArr': 'dArr',
                       'hArr': 'hArr',
                       'forall': 'forall',
                       'part': 'part',
                       'exist': 'exist',
                       'empty': 'empty',
                       'nabla': 'nabla',
                       'isin': 'isin',
                       'notin': 'notin',
                       'ni': 'ni',
                       'prod': 'prod',
                       'sum': 'sum',
                       'minus': 'minus',
                       'lowast': 'lowast',
                       'radic': 'radic',
                       'prop': 'prop',
                       'infin': 'infin',
                       'ang': 'ang',
                       'and': 'and',
                       'or': 'or',
                       'cap': 'cap',
                       'cup': 'cup',
                       'int': 'int',
                       'there4': 'there4',
                       'sim': 'sim',
                       'cong': 'cong',
                       'asymp': 'asymp',
                       'ne': 'ne',
                       'equiv': 'equiv',
                       'le': 'le',
                       'ge': 'ge',
                       'sub': 'sub',
                       'sup': 'sup',
                       'nsub': 'nsub',
                       'sube': 'sube',
                       'supe': 'supe',
                       'oplus': 'oplus',
                       'otimes': 'otimes',
                       'perp': 'perp',
                       'sdot': 'sdot',
                       'lceil': 'lceil',
                       'rceil': 'rceil',
                       'lfloor': 'lfloor',
                       'rfloor': 'rfloor',
                       'lang': 'lang',
                       'rang': 'rang',
                       'loz': 'loz',
                       'spades': 'spades',
                       'clubs': 'clubs',
                       'hearts': 'hearts',
                       'diams': 'diams',
                       'OElig': 'OElig',
                       'oelig': 'oelig',
                       'Scaron': 'Scaron',
                       'scaron': 'scaron',
                       'Yumlaut': 'Yuml',
                       'circ': 'circ',
                       'tilde': 'tilde',
                       'ensp': 'ensp',
                       'emsp': 'emsp',
                       'thinsp': 'thinsp',
                       'zwnj': 'zwnj',
                       'zwj': 'zwj',
                       'lrm': 'lrm',
                       'rlm': 'rlm',
                       'ndash': 'ndash',
                       'mdash': 'mdash',
                       'lsquo': 'lsquo',
                       'rsquo': 'rsquo',
                       'sbquo': 'sbquo',
                       'ldquo': 'ldquo',
                       'rdquo': 'rdquo',
                       'bdquo': 'bdquo',
                       'dagger': 'dagger',
                       'Dagger': 'Dagger',
                       'permil': 'permil',
                       'lsaquo': 'lsaquo',
                       'rsaquo': 'rsaquo',
                       'euro': 'euro',
                       'tm': 'trade'}
            try:
                entity = mapping[i.tag]
                out.parsed += '&{};'.format(entity)
            except: # pragma: no cover
                logging.warning("{}: ignoring <{}> in desc".format(state.current, i.tag))

        # Now we can reset previous_section to None, nobody needs it anymore.
        # Of course we're resetting it only in case nothing else (such as the
        # <simplesect> tag) could affect it in this iteration.
        if (i.tag != 'simplesect' or i.attrib['kind'] == 'return') and previous_section:
            previous_section = None

        # A custom inline CSS class was used (or was meant to be used) in this
        # iteration, reset it so it's not added again in the next iteration. If
        # this is a <mcss:class> element, it was added just now, don't reset
        # it.
        if i.tag != '{http://mcss.mosra.cz/doxygen/}class' and add_inline_css_class:
            add_inline_css_class = None

        # A custom block CSS class was used (or was meant to be used) in this
        # iteration, reset it so it's not added again in the next iteration. If
        # this is a paragraph, it might be added just now from within the
        # nested content, don't reset it.
        if i.tag != 'para' and add_css_class:
            add_css_class = None

        # DOXYGEN <PARA> PATCHING 4/4
        #
        # Besides putting notes and blockquotes and shit inside paragraphs,
        # Doxygen also doesn't attempt to open a new <para> for the ACTUAL NEW
        # PARAGRAPH after they end. So I do it myself and give a hint to the
        # caller that they should close the <p> again.
        if element.tag == 'para' and not out.write_paragraph_close_tag and i.tail and i.tail.strip():
            out.parsed += '<p>'
            out.write_paragraph_close_tag = True
            # There is usually some whitespace in between, get rid of it as
            # this is a start of a new paragraph. Stripping of the whole thing
            # is done by the caller.
            out.parsed += html.escape(i.tail.lstrip())

        # Otherwise strip if requested by the caller, if this is right after a
        # line break or a <mcss:div>, or if <mcss:class> was before (which
        # likely had a space before itself as well)
        elif i.tail:
            tail: str = html.escape(i.tail)
            if trim:
                tail = tail.strip()
            elif out.parsed.endswith('<br />') or i.tag in ['{http://mcss.mosra.cz/doxygen/}div', '{http://mcss.mosra.cz/doxygen/}class']:
                tail = tail.lstrip()
            out.parsed += tail

        # Remember the previous element. Needed by Doxygen 1.9
        # code-after-blockquote discovery.
        previous_element = i

    # A section was left open in the last iteration, close it. Expect that
    # there was nothing after that would mess with us.
    if previous_section:
        assert not out.write_paragraph_close_tag
        out.parsed = out.parsed.rstrip() + '</aside>'

    # Brief description always needs to be single paragraph because we're
    # sending it out without enclosing <p>.
    if element.tag == 'briefdescription':
        # JAVADOC_AUTOBRIEF / QT_AUTOBRIEF is *bad*
        if state.doxyfile.get('JAVADOC_AUTOBRIEF', False) or state.doxyfile.get('QT_AUTOBRIEF', False):
            # See the contents_autobrief_heading / contents_autobrief_hr test
            # for details (only on Doxygen <= 1.8.14, 1.8.15 doesn't seem to
            # put block elements into brief anymore)
            # TODO: remove along with the related test cases once 1.8.14
            # support can be dropped
            if has_block_elements:
                logging.warning("{}: JAVADOC_AUTOBRIEF / QT_AUTOBRIEF produced a brief description with block elements. That's not supported, ignoring the whole contents of {}".format(state.current, out.parsed))
                out.parsed = ''

            # See the contents_autobrief_multiline test for details. This also
            # blows up on 1.8.14 when \defgroup is followed by multiple lines
            # of text.
            elif paragraph_count > 1:
                logging.warning("{}: JAVADOC_AUTOBRIEF / QT_AUTOBRIEF produced a multi-line brief description. That's not supported, using just the first paragraph of {}".format(state.current, out.parsed))

                end = out.parsed.find('</p>')
                assert out.parsed.startswith('<p>') and end != -1
                out.parsed = out.parsed[3:end]

            elif paragraph_count == 1:
                assert out.parsed.startswith('<p>') and out.parsed.endswith('</p>')
                out.parsed = out.parsed[3:-4]

        # Sane behavior otherwise. Well, no. I give up.
        else:
            # In 1.8.15 if @brief is followed by an @ingroup, then the
            # immediately following paragraph gets merged with it for some
            # freaking reason. See the contents_brief_multiline_ingroup test
            # for details. Fixed since 1.8.16.
            #
            # In 1.8.18+, if ///> is accidentally used to mark "a docblock for
            # the following symbol", it leads to a <blockquote> contained in
            # the brief. Not much to do except for ignoring the whole thing.
            # See the contents_autobrief_blockquote test for details. Doesn't
            # happen in 1.12 anymore, not sure if that changed due to
            # https://github.com/doxygen/doxygen/issues/10902 or something
            # else in some earlier version.
            if has_block_elements or paragraph_count > 1:
                logging.warning("{}: ignoring brief description containing multiple paragraphs. Please modify your markup to remove any block elements from the following: {}".format(state.current, out.parsed))
                out.parsed = ''
            elif paragraph_count == 1:
                assert out.parsed.startswith('<p>') and out.parsed.endswith('</p>')
                out.parsed = out.parsed[3:-4]

    # Strip superfluous <p> for simple elements (list items, parameter and
    # return value description, table cells), but only if there is just a
    # single paragraph
    elif (element.tag in ['listitem', 'parameterdescription', 'entry'] or (element.tag == 'simplesect' and element.attrib['kind'] == 'return')) and not has_block_elements and paragraph_count == 1 and out.parsed:
        assert out.parsed.startswith('<p>') and out.parsed.endswith('</p>')
        out.parsed = out.parsed[3:-4]

    return out


def parse_desc(state: State, element: ET.Element) -> str:
    if element is None: return ''

    # Verify that we didn't ignore any important info by accident
    parsed = parse_desc_internal(state, element)
    assert not parsed.templates and not parsed.params and not parsed.return_value and not parsed.return_values
    assert not parsed.section # might be problematic
    return parsed.parsed

def parse_desc_keywords(state: State, element: ET.Element) -> Tuple[str, List[Tuple[str, str, int]], bool]:
    if element is None: return ''

    # Verify that we didn't ignore any important info by accident
    parsed = parse_desc_internal(state, element)
    assert not parsed.templates and not parsed.params and not parsed.return_value and not parsed.return_values and not parsed.exceptions
    assert not parsed.section # might be problematic
    return parsed.parsed, parsed.search_keywords, parsed.search_enum_values_as_keywords

def parse_enum_desc(state: State, element: ET.Element) -> Tuple[str, List[Tuple[str, str, int]], bool, bool]:
    parsed = parse_desc_internal(state, element.find('detaileddescription'))
    parsed.parsed += parse_desc(state, element.find('inbodydescription'))
    if parsed.templates or parsed.params or parsed.return_value or parsed.return_values or parsed.exceptions:
        logging.warning("{}: unexpected @tparam / @param / @return / @retval / @exception found in enum description, ignoring".format(state.current))
    assert not parsed.section # might be problematic
    return parsed.parsed, parsed.search_keywords, parsed.search_enum_values_as_keywords, parsed.deprecated, parsed.since

def parse_enum_value_desc(state: State, element: ET.Element) -> Tuple[str, List[Tuple[str, str, int]], bool]:
    parsed = parse_desc_internal(state, element.find('detaileddescription'))
    if parsed.templates or parsed.params or parsed.return_value or parsed.return_values or parsed.exceptions:
        logging.warning("{}: unexpected @tparam / @param / @return / @retval / @exception found in enum value description, ignoring".format(state.current))
    assert not parsed.section # might be problematic
    return parsed.parsed, parsed.search_keywords, parsed.deprecated, parsed.since

def parse_var_desc(state: State, element: ET.Element) -> Tuple[str, List[Any], List[Tuple[str, str, int]], bool]:
    parsed = parse_desc_internal(state, element.find('detaileddescription'))
    parsed.parsed += parse_desc(state, element.find('inbodydescription'))
    if parsed.params or parsed.return_value or parsed.return_values or parsed.exceptions:
        logging.warning("{}: unexpected @param / @return / @retval / @exception found in variable description, ignoring".format(state.current))
    assert not parsed.section # might be problematic
    return parsed.parsed, parsed.templates, parsed.search_keywords, parsed.deprecated, parsed.since

def parse_toplevel_desc(state: State, element: ET.Element) -> Tuple[str, List[Any], str, Any, Any, List[Tuple[str, str, int]], bool]:
    state.parsing_toplevel_desc = True
    parsed = parse_desc_internal(state, element)
    state.parsing_toplevel_desc = False
    if parsed.params or parsed.return_value or parsed.return_values or parsed.exceptions:
        logging.warning("{}: unexpected @param / @return / @retval / @exception found in top-level description, ignoring".format(state.current))
    return parsed.parsed, parsed.templates, parsed.section[2] if parsed.section else '', parsed.footer_navigation, parsed.example_navigation, parsed.search_keywords, parsed.deprecated, parsed.since

def parse_typedef_desc(state: State, element: ET.Element) -> Tuple[str, List[Any], List[Tuple[str, str, int]], bool]:
    parsed = parse_desc_internal(state, element.find('detaileddescription'))
    parsed.parsed += parse_desc(state, element.find('inbodydescription'))
    if parsed.params or parsed.return_value or parsed.return_values or parsed.exceptions:
        logging.warning("{}: unexpected @param / @return / @retval / @exception found in typedef description, ignoring".format(state.current))
    assert not parsed.section # might be problematic
    return parsed.parsed, parsed.templates, parsed.search_keywords, parsed.deprecated, parsed.since

def parse_func_desc(state: State, element: ET.Element) -> Tuple[str, List[Any], List[Any], str, List[Any], List[Any], List[Tuple[str, str, int]], bool]:
    parsed = parse_desc_internal(state, element.find('detaileddescription'))
    parsed.parsed += parse_desc(state, element.find('inbodydescription'))
    assert not parsed.section # might be problematic
    return parsed.parsed, parsed.templates, parsed.params, parsed.return_value, parsed.return_values, parsed.exceptions, parsed.search_keywords, parsed.deprecated, parsed.since

def parse_define_desc(state: State, element: ET.Element) -> Tuple[str, List[Any], str, List[Tuple[str, str, int]], bool]:
    parsed = parse_desc_internal(state, element.find('detaileddescription'))
    parsed.parsed += parse_desc(state, element.find('inbodydescription'))
    if parsed.templates or parsed.return_values or parsed.exceptions:
        logging.warning("{}: unexpected @tparam / @retval / @exception found in macro description, ignoring".format(state.current))
    assert not parsed.section # might be problematic
    return parsed.parsed, parsed.params, parsed.return_value, parsed.search_keywords, parsed.deprecated, parsed.since

def parse_inline_desc(state: State, element: ET.Element) -> str:
    if element is None: return ''

    # Verify that we didn't ignore any important info by accident
    parsed = parse_desc_internal(state, element, trim=False)
    assert not parsed.templates and not parsed.params and not parsed.return_value and not parsed.return_values and not parsed.exceptions
    assert not parsed.section
    return parsed.parsed

def parse_enum(state: State, element: ET.Element):
    logging.debug(f"Parsing enum {element.find('name').text} in file {state.current}")
    if element.tag !='memberdef':
        logging.warning(f"Ignoring enum {element.find('name').text} in {state.current} because it is not a memberdef")
        return
    assert element.tag == 'memberdef' and element.attrib['kind'] == 'enum'

    enum = Empty()
    state.current_definition_url_base, enum.base_url, enum.id, enum.include, enum.has_details = parse_id_and_include(state, element)
    enum.type = parse_type(state, element.find('type'))
    enum.name = element.find('name').text
    # Doxygen < 1.9.7 puts a generated name into the XML, starting with @,
    # newer versions strip those away, leading to an empty name
    # https://github.com/doxygen/doxygen/commit/a18e4c76ed6415893800c7d77a2f798614fb638b
    if not enum.name or enum.name.startswith('@'):
        enum.name = '(anonymous)'
    enum.brief = parse_desc(state, element.find('briefdescription'))
    enum.description, search_keywords, search_enum_values_as_keywords, enum.deprecated, enum.since = parse_enum_desc(state, element)
    enum.is_protected = element.attrib['prot'] == 'protected'
    enum.is_strong = False
    if 'strong' in element.attrib:
        enum.is_strong = element.attrib['strong'] == 'yes'
    enum.values = []

    enum.has_value_details = False
    enumvalue: ET.Element
    for enumvalue in element.findall('enumvalue'):
        value = Empty()
        # The base_url might be different than state.current_compound.url, but
        # should be the same as enum.base_url
        value.id = extract_id_hash(state, enumvalue)
        value.name = enumvalue.find('name').text
        # There can be an implicit initializer for enum value
        value.initializer = html.escape(enumvalue.findtext('initializer', ''))
        value.brief = parse_desc(state, enumvalue.find('briefdescription'))
        value.description, value_search_keywords, value.deprecated, value.since = parse_enum_value_desc(state, enumvalue)
        if value.brief or value.description:
            if enum.base_url == state.current_compound_url and not state.config['SEARCH_DISABLED']:
                result = Empty()
                result.flags = ResultFlag.from_type(ResultFlag.DEPRECATED if value.deprecated else ResultFlag(0), EntryType.ENUM_VALUE)
                result.url = enum.base_url + '#' + value.id
                result.prefix = state.current_prefix + [enum.name]
                result.name = value.name
                result.keywords = value_search_keywords
                if search_enum_values_as_keywords and value.initializer.startswith('='):
                    result.keywords += [(value.initializer[1:].lstrip(), '', 0)]
                state.search += [result]

            # If either brief or description for this value is present, we want
            # to show the detailed enum docs. However, in case
            # SHOW_UNDOCUMENTED is enabled, the values might have just a dummy
            # <span></span> content in order to make them "appear documented".
            # Then it doesn't make sense to repeat the same list twice.
            if not state.config['SHOW_UNDOCUMENTED'] or value.brief != '<span></span>':
                enum.has_value_details = True

        enum.values += [value]

    if enum.base_url == state.current_compound_url and (enum.description or enum.has_value_details):
        enum.has_details = True # has_details might already be True from above
    if enum.brief or enum.has_details or enum.has_value_details:
        if enum.base_url == state.current_compound_url and not state.config['SEARCH_DISABLED']:
            result = Empty()
            result.flags = ResultFlag.from_type(ResultFlag.DEPRECATED if enum.deprecated else ResultFlag(0), EntryType.ENUM)
            result.url = enum.base_url + '#' + enum.id
            result.prefix = state.current_prefix
            result.name = enum.name
            result.keywords = search_keywords
            state.search += [result]
        return enum
    return None

def parse_template_params(state: State, element: ET.Element, description):
    if element is None: return False, None
    assert element.tag == 'templateparamlist'

    has_template_details = False
    templates = []
    i: ET.Element
    for i in element:
        assert i.tag == 'param'

        template = Empty()
        template.type = parse_type(state, i.find('type'))
        declname = i.find('declname')
        if declname is not None:
            # declname or decltype?!
            template.name = declname.text
        # Doxygen sometimes puts both in type, extract that, but only in case
        # it's not too crazy to do (i.e., no pointer values, no nameless
        # FooBar<T, U> types). Using rpartition() to split on the last found
        # space, but in case of nothing found, rpartition() puts the full
        # string into [2] instead of [0], so we have to account for that.
        elif template.type[-1].isalnum():
            parts = template.type.rpartition(' ')
            if parts[1]:
                template.type = parts[0]
                template.name = parts[2]
            else:
                template.type = parts[2]
                template.name = ''
        else:
            template.name = ''
        default = i.find('defval')
        template.default = parse_type(state, default) if default is not None else ''
        if template.name in description:
            template.description = description[template.name]
            del description[template.name]
            has_template_details = True
        else:
            template.description = ''
        templates += [template]

    # Some param description got unused
    if description:
        logging.warning("{}: template parameter description doesn't match parameter names: {}".format(state.current, repr(description)))

    return has_template_details, templates

def parse_typedef(state: State, element: ET.Element):
    logging.debug(
        f"Parsing typedef {element.find('name').text} of kind {element.attrib['kind']} with tag {element.tag} in file {state.current}"
    )
    if element.tag !='memberdef':
        logging.warning(f"Ignoring typedef {element.find('name').text} in {state.current} because it is not a memberdef")
        return
    assert element.tag == 'memberdef' and element.attrib['kind'] == 'typedef'

    typedef = Empty()
    state.current_definition_url_base, typedef.base_url, typedef.id, typedef.include, typedef.has_details = parse_id_and_include(state, element)
    typedef.is_using = element.findtext('definition', '').startswith('using')
    typedef.type = parse_type(state, element.find('type'))
    typedef.args = parse_type(state, element.find('argsstring'))
    typedef.name = element.find('name').text
    typedef.brief = parse_desc(state, element.find('briefdescription'))
    typedef.description, templates, search_keywords, typedef.deprecated, typedef.since = parse_typedef_desc(state, element)
    typedef.is_protected = element.attrib['prot'] == 'protected'
    typedef.has_template_details, typedef.templates = parse_template_params(state, element.find('templateparamlist'), templates)

    if typedef.base_url == state.current_compound_url and (typedef.description or typedef.has_template_details):
        typedef.has_details = True # has_details might already be True from above
    if typedef.brief or typedef.has_details:
        # Avoid duplicates in search
        if typedef.base_url == state.current_compound_url and not state.config['SEARCH_DISABLED']:
            result = Empty()
            result.flags = ResultFlag.from_type(ResultFlag.DEPRECATED if typedef.deprecated else ResultFlag(0), EntryType.TYPEDEF)
            result.url = typedef.base_url + '#' + typedef.id
            result.prefix = state.current_prefix
            result.name = typedef.name
            result.keywords = search_keywords
            state.search += [result]
        return typedef
    return None

def parse_func(state: State, element: ET.Element):
    logging.debug(
        f"Parsing function {fix_type_spacing(html.escape(element.find('name').text))} of kind {element.attrib['kind']} with tag {element.tag} in file {state.current}"
    )
    assert element.tag == 'memberdef' and element.attrib['kind'] in ['function', 'friend', 'signal', 'slot']

    func = Empty()
    state.current_definition_url_base, func.base_url, func.id, func.include, func.has_details = parse_id_and_include(state, element)
    func.type = parse_type(state, element.find('type'))
    func.name = fix_type_spacing(html.escape(element.find('name').text))
    func.brief = parse_desc(state, element.find('briefdescription'))
    func.description, templates, params, func.return_value, func.return_values, func.exceptions, search_keywords, func.deprecated, func.since = parse_func_desc(state, element)

    def is_identifier(a): return a == '_' or a.isalnum()

    # Extract function signature to prefix, suffix and various flags. Important
    # things affecting caller such as static or const (and rvalue overloads)
    # are put into signature prefix/suffix, other things to various is_*
    # properties.
    #
    # First the prefix keywords - Doxygen has a habit of leaking attributes and
    # other specifiers into the function's return type, and not necessarily
    # in any consistent order (including swapping it with the actual type!)
    exposed_attribute_keywords = [
        'constexpr',
        'consteval',
        'explicit',
        'virtual'
    ]
    ignored_attribute_keywords = [
        'static', # Included in func.prefix already
        'friend',
        'inline'
    ]
    for kw in exposed_attribute_keywords:
        setattr(func, 'is_' + kw, False)
    is_static = False
    matched_bad_keyword = True
    while matched_bad_keyword:
        matched_bad_keyword = False
        for kw in exposed_attribute_keywords + ignored_attribute_keywords:
            if func.type == kw: # constructors
                func.type = ''
            elif func.type.startswith(kw + ' '):
                func.type = func.type[len(kw):].strip()
            elif func.type.endswith(' ' + kw):
                # Uncovered; since 1.8.16 the keyword/type ordering (with
                # decltype(auto), see the cpp_function_attributes test for a
                # repro case) has not been a problem, but this handling is left
                # as a future-proofing mechanism.
                func.type = func.type[:len(kw)].strip()
            else:
                continue
            matched_bad_keyword = True
            if kw in exposed_attribute_keywords:
                setattr(func, 'is_' + kw, True)
            elif kw == 'static':
                is_static = True
    # Merge any leaked attributes with their corresponding XML attributes to
    # account for the situation where Doxygen has only half got it right
    # (which, honestly, is most of the time)
    func.is_explicit = func.is_explicit or element.attrib['explicit'] == 'yes'
    func.is_virtual = func.is_virtual or element.attrib['virt'] != 'non-virtual'
    is_static = is_static or element.attrib['static'] == 'yes'
    if 'constexpr' in element.attrib:
        func.is_constexpr = func.is_constexpr or element.attrib['constexpr'] == 'yes'
    if 'consteval' in element.attrib:
        # consteval XML attribute is since Doxygen 1.9, earlier versions keep
        # the keyword in the signature
        func.is_consteval = func.is_consteval or element.attrib['consteval'] == 'yes'
    func.prefix = ''
    if is_static:
        func.prefix += 'static '
    # Extract additional C++11 stuff from the signature. Order matters, going
    # from the keywords that can be rightmost to the leftmost.
    signature: str = element.find('argsstring').text
    if signature is not None and signature.endswith('=default'):
        signature = signature[:-8]
        func.is_defaulted = True
    else:
        func.is_defaulted = False
    if signature is not None and signature.endswith('=delete'):
        signature = signature[:-7]
        func.is_deleted = True
    else:
        func.is_deleted = False
    if signature is not None and signature.endswith('=0'):
        signature = signature[:-2]
        func.is_pure_virtual = True
    else:
        func.is_pure_virtual = False
    # Final tested twice because it can be both `override final`
    func.is_final = False
    if signature is not None and signature.endswith('final') and not is_identifier(signature[-6]):
        signature = signature[:-5].rstrip()
        func.is_final = True
    if signature is not None and signature.endswith('override') and not is_identifier(signature[-9]):
        signature = signature[:-8].rstrip()
        func.is_override = True
    else:
        func.is_override = False
    # ... and `final override`
    if signature is not None and signature.endswith('final') and not is_identifier(signature[-6]):
        signature = signature[:-5].rstrip()
        func.is_final = True
    if signature is not None and signature.endswith('noexcept') and not is_identifier(signature[-9]):
        signature = signature[:-8].rstrip()
        func.is_noexcept = True
        func.is_conditional_noexcept = False
    elif signature is not None and 'noexcept(' in signature and not is_identifier(signature[signature.index('noexcept(') - 1]):
        signature = signature[:signature.index('noexcept(')].rstrip()
        func.is_noexcept = True
        func.is_conditional_noexcept = True
    else:
        func.is_noexcept = False
        func.is_conditional_noexcept = False
    # Noexcept can be also an attribute (since 1.8.16), merge with that. Until
    # https://github.com/doxygen/doxygen/commit/b51d6d2dd2cb6a4945a3775a649e7eca8e120515
    # (1.11) it seems it was present both in the signature and in the attribs.
    if 'noexcept' in element.attrib:
        func.is_noexcept = func.is_noexcept or element.attrib['noexcept'] == 'yes'
    # noexceptexpression is since 1.11. If not present, it's not conditionally
    # noexcept.
    if 'noexceptexpression' in element.attrib:
        func.is_conditional_noexcept = True
    # Put the rest (const, volatile, ...) into a suffix
    if signature is not None:
        func.suffix = html.escape(signature[signature.rindex(')') + 1:].strip())
    else:
        func.suffix = ''
    if func.suffix: func.suffix = ' ' + func.suffix
    # Protected / private makes no sense for friend functions
    if element.attrib['kind'] != 'friend':
        func.is_protected = element.attrib['prot'] == 'protected'
        func.is_private = element.attrib['prot'] == 'private'
    func.is_signal = element.attrib['kind'] == 'signal'
    func.is_slot = element.attrib['kind'] == 'slot'

    func.has_template_details, func.templates = parse_template_params(state, element.find('templateparamlist'), templates)

    func.has_param_details = False
    func.params = []
    for p in element.findall('param'):
        name = p.find('declname')
        param = Empty()
        param.name = name.text if name is not None else ''
        param_type = p.find('type')
        if param_type is None:
            logging.warning("{}: parameter {} of function {} has no type, ignoring the whole function as it's suspected to be a mishandled macro call".format(state.current, param.name, func.name))
            return None
        param.type = parse_type(state, param_type)

        # Recombine parameter name and array information back
        array = p.find('array')
        if array is not None:
            if name is not None:
                if param.type.endswith(')'):
                    param.type_name = param.type[:-1] + name.text + ')' + array.text
                else:
                    param.type_name = param.type + ' ' + name.text + array.text
            else:
                param.type_name = param.type + array.text
            param.type += array.text
        elif name is not None:
            param.type_name = param.type + ' ' + name.text
        else:
            param.type_name = param.type

        param.default = parse_type(state, p.find('defval'))
        if param.name in params:
            param.description, param.direction = params[param.name]
            del params[param.name]
            func.has_param_details = True
        else:
            param.description, param.direction = '', ''
        func.params += [param]

    # Some param description got unused
    if params: logging.warning("{}: function parameter description doesn't match parameter names: {}".format(state.current, repr(params)))

    # If there's a detailed description or template, param, return value or
    # exception details, the function can have a detailed block
    #
    # This also means has_details is always False for functions in
    # namespaces referenced from header file docs.
    can_have_details = func.description or func.has_template_details or func.has_param_details or func.return_value or func.return_values or func.exceptions

    # If we're in the compound where the function originates (so in the
    # namespace where the function is and not in a header file docs which
    # reference functions from that namespace)
    if func.base_url == state.current_compound_url:
        # This means has_details is always False for namespace functions
        # referenced from header file docs -- if it wouldn't be, the same docs
        # would be shown both in the namespace and in file docs, which is a
        # useless duplication.
        #
        # The has_details might also already be True from above when we need to
        # show a different include than the global compound include.
        if can_have_details:
            func.has_details = True

        # Then, if the function has some actual documentation, add it to the
        # search. Again, the compound URL check means the search entry is not
        # duplicated for functions referenced from file docs.
        if (func.brief or func.has_details) and not state.config['SEARCH_DISABLED']:
            result = Empty()
            result.flags = ResultFlag.from_type((ResultFlag.DEPRECATED if func.deprecated else ResultFlag(0))|(ResultFlag.DELETED if func.is_deleted else ResultFlag(0)), EntryType.FUNC)
            result.url = func.base_url + '#' + func.id
            result.prefix = state.current_prefix
            result.name = func.name
            result.keywords = search_keywords
            result.params = [param.type for param in func.params]
            result.suffix = func.suffix
            state.search += [result]

    # Fix up duplicated return types within the return description
    if (func.type is not None and len(func.type) > 0) and (
        func.return_value is not None and len(func.return_value) > 0
    ):
        if func.return_value.startswith(func.type):
            func.return_value = func.return_value.replace(func.type, "", 1).lstrip()
        elif func.return_value.startswith(f"<em>{func.type}</em>"):
            func.return_value = func.return_value.replace(
                f"<em>{func.type}</em>", "", 1
            ).lstrip()

    # Return the function only if it has some documentation. Testing just for
    # func.has_details would erroneously omit functions that have e.g. just
    # /** @overload */ from file docs.
    return func if func.brief or can_have_details else None

def parse_var(state: State, element: ET.Element):
    logging.debug(
        f"Parsing variable {fix_type_spacing(html.escape(element.find('name').text))} of kind {element.attrib['kind']} with tag {element.tag} in file {state.current}"
    )
    assert element.tag == 'memberdef' and element.attrib['kind'] == 'variable'

    var = Empty()
    state.current_definition_url_base, var.base_url, var.id, var.include, var.has_details = parse_id_and_include(state, element)
    var.type = parse_type(state, element.find('type'))
    if var.type.startswith('constexpr'):
        var.type = var.type[10:]
        var.is_constexpr = True
    else:
        var.is_constexpr = False
    # When 1.8.18 encounters `constexpr static`, it keeps the static there. For
    # `static constexpr` it doesn't. In both cases the static="yes" is put
    # there correctly. Same case is for functions, although there it's further
    # complicated with other possible keyword combinations. Fixed in 1.11.
    if var.type.startswith('static'):
        var.type = var.type[7:]
    # Constexpr can be also an attribute, merge with that. Until
    # https://github.com/doxygen/doxygen/commit/b51d6d2dd2cb6a4945a3775a649e7eca8e120515
    # (1.11) it seems it was present both in the signature and in the attribs.
    if 'constexpr' in element.attrib:
        var.is_constexpr = var.is_constexpr or element.attrib['constexpr'] == 'yes'
    var.is_static = element.attrib['static'] == 'yes'
    var.is_protected = element.attrib['prot'] == 'protected'
    var.is_private = element.attrib['prot'] == 'private'
    var.name = element.find('name').text
    var.brief = parse_desc(state, element.find('briefdescription'))
    var.description, templates, search_keywords, var.deprecated, var.since = parse_var_desc(state, element)
    var.has_template_details, var.templates = parse_template_params(state, element.find('templateparamlist'), templates)

    if var.base_url == state.current_compound_url and (var.description or var.has_template_details):
        var.has_details = True # has_details might already be True from above
    if var.brief or var.has_details:
        # Avoid duplicates in search
        if var.base_url == state.current_compound_url and not state.config['SEARCH_DISABLED']:
            result = Empty()
            result.flags = ResultFlag.from_type(ResultFlag.DEPRECATED if var.deprecated else ResultFlag(0), EntryType.VAR)
            result.url = var.base_url + '#' + var.id
            result.prefix = state.current_prefix
            result.name = var.name
            result.keywords = search_keywords
            state.search += [result]
        return var
    return None

def parse_define(state: State, element: ET.Element):
    logging.debug(
        f"Parsing define {element.find('name').text} with tag {element.tag} in file {state.current}"
    )
    if element.tag !='memberdef':
        logging.warning(f"Ignoring define {element.find('name').text} in {state.current} because it is not a memberdef")
        return
    assert element.tag == 'memberdef' and element.attrib['kind'] == 'define'

    define = Empty()
    state.current_definition_url_base, define.base_url, define.id, define.include, define.has_details = parse_id_and_include(state, element)
    define.name = element.find('name').text
    define.initializer = element.find('initializer').text if element.find('initializer') is not None else None
    define.brief = parse_desc(state, element.find('briefdescription'))
    define.description, params, define.return_value, search_keywords, define.deprecated, define.since = parse_define_desc(state, element)
    define.has_param_details = False
    define.params = None
    for p in element.findall('param'):
        if define.params is None: define.params = []
        name = p.find('defname')
        if name is not None:
            if name.text in params:
                description, _ = params[name.text]
                del params[name.text]
                define.has_param_details = True
            else:
                description = ''
            define.params += [(name.text, description)]

    # Some param description got unused
    if params: logging.warning("{}: define parameter description doesn't match parameter names: {}".format(state.current, repr(params)))

    if define.base_url == state.current_compound_url and (define.description or define.return_value):
        define.has_details = True # has_details might already be True from above
    if define.brief or define.has_details:
        # Avoid duplicates in search
        if define.base_url == state.current_compound_url and not state.config['SEARCH_DISABLED']:
            result = Empty()
            result.flags = ResultFlag.from_type(ResultFlag.DEPRECATED if define.deprecated else ResultFlag(0), EntryType.DEFINE)
            result.url = define.base_url + '#' + define.id
            result.prefix = []
            result.name = define.name
            result.keywords = search_keywords
            result.params = None if define.params is None else [param[0] for param in define.params]
            state.search += [result]
        return define
    return None


# Used for the M_SHOW_UNDOCUMENTED option
def _document_all_stuff(compounddef: ET.Element):
    for i in compounddef.findall('.//briefdescription/..'):
        brief = i.find('briefdescription')
        # ElementTree deprecated the __bool__ conversion of Element, so I now
        # have to check that `detaileddescription` actually has any children.
        # Checking against None is not enough as it could be present but be
        # empty.
        if not len(brief) and not len(i.find('detaileddescription')):
            # Add an empty <span> to the paragraph so it doesn't look empty.
            # Can't use strong/emphasis, as those are collapsed if empty as
            # well; on the other hand it's very unlikely that someone would
            # want to use @m_span with empty contents.
            dim = ET.Element('{http://mcss.mosra.cz/doxygen/}span')
            para = ET.Element('para')
            para.append(dim)
            brief.append(para)


def is_a_stupid_empty_markdown_page(compounddef: ET.Element):
    assert compounddef.attrib['kind'] == 'page'

    # Doxygen creates a page for *all* markdown files even thought they
    # otherwise contain absolutely NOTHING except for symbol documentation.
    # And of course it's nearly impossible to distinguish those unwanted pages
    # from actually wanted (but empty) pages so at least I'm filtering out
    # everything that starts with md_ and ends with the same thing as the title
    # (which means there's no explicit title). We *do* want to preserve empty
    # pages with custom titles.
    is_stupid = (
        compounddef.find("compoundname").text.startswith("md_")
        and compounddef.find("compoundname").text.endswith(
            compounddef.find("title").text
        )
            and len(compounddef.find("briefdescription")) == 0
            and len(compounddef.find("detaileddescription")) == 0
        )
    logging.debug(
        f"{compounddef.attrib['id']} {'is a stupid markdown page' if is_stupid else 'seems to usable markdown'}"
    )
    return is_stupid

def extract_metadata(state: State, xml):
    # parse_desc() / parse_inline_desc() is called from here, be sure to set
    # current filename so it's reflected in possible warnings
    state.current = os.path.basename(xml)

    # These early returns should be kept consistent with parse_xml()
    if state.current == 'Doxyfile.xml':
        logging.debug("Ignoring {}".format(state.current))
        return

    logging.debug("Extracting metadata from {}".format(state.current))

    try:
        tree = ET.parse(xml)
    except ET.ParseError as e:
        logging.error("{}: XML parse error, skipping whole file: {}".format(state.current, e))
        return

    root = tree.getroot()

    # From index.xml we need just list of all example files in correct order,
    # nothing else
    if state.current == 'index.xml':
        for i in root:
            if i.attrib['kind'] == 'example':
                compound = Empty()
                compound.id = i.attrib['refid']
                compound.url = compound.id + '.html'
                compound.name = i.find('name').text
                state.examples += [compound]
        return

    # From other files we expect <doxygen><compounddef>
    if root.tag != 'doxygen':
        logging.warning("{}: root element expected to be <doxygen> but is <{}>, skipping whole file".format(state.current, root.tag))
        return
    compounddef: ET.Element = root[0]
    if compounddef.tag != 'compounddef':
        logging.warning("{}: first child element expected to be <compounddef> but is <{}>, skipping whole file".format(state.current, compounddef.tag))
        return
    # Using `in []` to prepare for potential future additions like 'C', but so
    # far Doxygen treats even *.c files as language="C++". Reproduced in the
    # test_ignored.Languages test case.
    if compounddef.attrib.get('language', 'C++') not in ['C++']:
        #NOTE: Don't bother to warn about stupid markdown pages
        if compounddef.attrib.get('language', 'C++') not in ['Markdown']:
            logging.warning("{}: unsupported language {}, skipping whole file".format(state.current, compounddef.attrib['language']))
        return
    assert len([i for i in root]) == 1

    if compounddef is None or len(compounddef) == 0:
        logging.debug("No useful info in {}, skipping".format(os.path.basename(xml)))
        return

    if compounddef.attrib['kind'] not in ['namespace', 'group', 'class', 'struct', 'union', 'dir', 'file', 'page']:
        logging.debug("No useful info in {}, skipping".format(state.current))
        return

    # In order to show also undocumented members, go through all empty
    # <briefdescription>s and fill them with a generic text.
    if state.config['SHOW_UNDOCUMENTED']:
        _document_all_stuff(compounddef)

    compound = StateCompound()
    compound.id  = compounddef.attrib['id']
    compound.kind = compounddef.attrib['kind']
    # Compound name is page filename, so we have to use title there. The same
    # is for groups. In some cases, such as anonymous namespaces in Doxygen
    # 1.9.7+, <compoundname> is empty. Corresponding test case is in
    # test_compound.Ignored. https://github.com/doxygen/doxygen/commit/a18e4c76ed6415893800c7d77a2f798614fb638b
    compound.name = html.escape(compounddef.find('title').text if compound.kind in ['page', 'group'] and compounddef.findtext('title') else compounddef.findtext('compoundname'))
    # Compound URL is ID, except for index page, where it is named "indexpage"
    # and so I have to override it back to "index". Can't use <compoundname>
    # for pages because that doesn't reflect CASE_SENSE_NAMES. THANKS DOXYGEN.
    # This is similar to compound.url_base handling in parse_xml() below.
    compound.url = 'index.html' if compound.kind == 'page' and compound.id == 'indexpage' else compound.id + '.html'
    compound.brief = parse_desc(state, compounddef.find('briefdescription'))
    # Groups are explicitly created so they *have details*, other
    # things need to have at least some documentation. Pages are treated as
    # having something unless they're stupid. See the function for details.
    #
    # ElementTree deprecated the __bool__ conversion of Element, so I now have
    # to check that `detaileddescription` actually has any children. Checking
    # against None is not enough as it could be present but be empty.
    compound.has_details = compound.kind == 'group' or len(compound.brief) > 0 or len(compounddef.find('detaileddescription')) or (compound.kind == 'page' and not is_a_stupid_empty_markdown_page(compounddef))
    compound.children = []
    compound.childrenClasses = []
    compound.childrenNamespaces = []
    compound.childrenCompoundRefs = []

    # Version badges, deprecation status. If @since is followed by
    # @deprecated, treat it as version in which given feature was deprecated
    compound.deprecated = None
    compound.since = None
    if state.config['VERSION_LABELS']:
        for i in compounddef.find('detaileddescription').findall('.//simplesect'):
            if i.attrib['kind'] != 'since': continue
            since = parse_inline_desc(state, i).strip()
            assert since.startswith('<p>') and since.endswith('</p>')
            compound.since = since[3:-4]
    for i in compounddef.find('detaileddescription').findall('.//xrefsect'):
        id = i.attrib['id']
        match = xref_id_rx.match(id)
        file = match.group(1)
        if file.startswith('deprecated'):
            if compound.since:
                compound.deprecated = compound.since
                compound.since = None
            else:
                compound.deprecated = 'deprecated'
            break

    # Inline namespaces
    if compound.kind == 'namespace':
        compound.is_inline = compounddef.attrib.get('inline') == 'yes'

    # Final classes
    if compound.kind in ['struct', 'class', 'union']:
        compound.is_final = compounddef.attrib.get('final') == 'yes'

    if compound.kind in ['class', 'struct', 'union']:
        # Fix type spacing
        compound.name = fix_type_spacing(compound.name)

        # Parse template list for classes
        _, compound.templates = parse_template_params(state, compounddef.find('templateparamlist'), {})

    # Find members of user-defined "member groups" (these have the tag 'sectiondef' with the kind 'user-defined').
    # These are called "member groups" in the Doxygen grouping documentation: https://www.doxygen.nl/manual/grouping.html
    # Member groups are defined with ///@{ ... ///@} or /**@{*/ ... /**@}*/
    # They don't have a @defgroup and group_label associated with them, just a name and maybe a description.
    # When member groups are nested inside of other groupings, instead of the sub-grouping being listed as an "inner___",
    # on the grand-parent, the grand-parent contains a copy of the name and description for the inner-member-group and subset references to members.
    # Prior to https://github.com/doxygen/doxygen/pull/9797, the full memberdef was listed in the xml of both the
    # parent and grandparent. Changes were made in response to this issue: https://github.com/doxygen/doxygen/issues/8790
    for compounddef_child in compounddef.findall('sectiondef'):
        if compounddef_child.attrib['kind'] in ['user-defined']:
            member_list = [] # only references
            memberdef_list = [] #fully defined members

            member: ET.Element
            for member in compounddef_child.findall('member'):
                # These are the kinds supported within user-defined sections in the parse_xml function
                if member.attrib['kind'] in ['enum', 'typedef', 'function', 'signal', 'slot', 'variable', 'define', 'friend']:
                    member_list += [member.attrib['refid']]
                else: # pragma: no cover
                    logging.warning("{}: unknown member kind within member group {}".format(state.current, member.attrib['kind']))
            memberdef: ET.Element
            for memberdef in compounddef_child.findall('memberdef'):
                # These are the kinds supported within user-defined sections in the parse_xml function
                if memberdef.attrib['kind'] in ['enum', 'typedef', 'function', 'signal', 'slot', 'variable', 'define', 'friend']:
                    memberdef_list += [memberdef.attrib['id']]
                else: # pragma: no cover
                    logging.warning("{}: unknown memberdef kind within member group {}".format(state.current, memberdef.attrib['kind']))

            logging.debug("{}: member group found in user-defined section with {} reference members and {} full member-defs when extracting metadata".format(state.current, len(member_list), len(memberdef_list)))

            # if we got only "members" defined elsewhere, this member group like an 'inner-group' and we'll add it like a child
            if len(member_list) and not len(memberdef_list):
                header = compounddef_child.find('header')
                if header is None:
                    logging.error("{}: member groups without @name are not supported, ignoring".format(state.current))
                member_group_name = header.text
                member_group_id=slugify(member_group_name)
                compound.children += [member_group_id]
            # if we only got complete memberdefs in this member group, then we can defer processing those members until parsing the xml in the next step
            elif not len(member_list) and len(memberdef_list):
                pass
            # if it's a mix.. (not sure if this is possible) we'll do nothing but throw a warning
            else:
                logging.warning("Got a member group with both fully defined members and referenced members. The referenced members will be ignored!")

    # Files have <innerclass> and <innernamespace> but that's not what we want,
    # so separate the children queries based on compound type

    # namespaces, classes, structs, and unions can have inner-classes, inner-namespaces, and inner-derived-compound-references
    if compounddef.attrib['kind'] in ['namespace', 'class', 'struct', 'union']:
        for i in compounddef.findall('innerclass'):
            compound.children += [i.attrib['refid']]
        for i in compounddef.findall('innernamespace'):
            # Children of inline namespaces get listed also in their parents as
            # of 1.9.0 and https://github.com/doxygen/doxygen/commit/4372054e0b7af9c0cd1c1390859d8fef3581d8bb
            # So e.g. if Bar is inline, Foo::Bar::Baz gets shortened to
            # Foo::Baz, and listed as <innernamespace> of both Foo and
            # Foo::Bar. Compare their IDs (because they don't get shortened)
            # and add the namespace only if it's a direct descendant. Another
            # patching gets done in postprocess_state() below, then the same
            # child filtering is done in parse_xml(), and finally the
            # duplicates have to be removed in parse_index_xml() as well. See
            # test_compound.InlineNamespace for a matching test case.
            if i.attrib['refid'].rpartition('_1_1')[0] == compound.id:
                compound.children += [i.attrib['refid']]
        for i in compounddef.findall('derivedcompoundref'):
            compound.children += [i.attrib['refid']]
    # directories and files can have inner-directories and inner-files
    elif compounddef.attrib['kind'] in ['dir', 'file']:
        for i in compounddef.findall('innerdir'):
            compound.children += [i.attrib['refid']]
        for i in compounddef.findall('innerfile'):
            compound.children += [i.attrib['refid']]
    # pages can only have inner-pages
    elif compounddef.attrib['kind'] == 'page':
        for i in compounddef.findall(".//innerpage"):
            compound.children += [i.attrib['refid']]
    # groups (aka topics or modules) can have inner-groups, inner-classes, inner-namespaces, and inner-derived-compound-references
    elif compounddef.attrib['kind'] == 'group':
        for i in compounddef.findall('innergroup'):
            compound.children += [i.attrib['refid']]
        for i in compounddef.findall('innerclass'):
            compound.childrenClasses += [i.attrib['refid']]
        for i in compounddef.findall('innernamespace'):
            compound.childrenNamespaces += [i.attrib['refid']]
        for i in compounddef.findall('derivedcompoundref'):
            compound.childrenCompoundRefs += [i.attrib['refid']]

    state.compounds[compound.id] = compound

    output = os.path.join(
        os.path.join(state.basedir, state.doxyfile['OUTPUT_DIRECTORY'], state.doxyfile['HTML_OUTPUT']), compound.id + '_metadata.json'
    )
    with open(output, "w", encoding="utf8") as f:
        json.dump(compound, f, cls=MappingProxyEncoder, indent=2)


def postprocess_state(state: State):
    # Save parent for each child
    for _, compound in state.compounds.items():
        for child in compound.children:
            if child in state.compounds:
                state.compounds[child].parent = compound.id
        for child in compound.childrenClasses:
            if child in state.compounds:
                state.compounds[child].parentGroup = compound.id
        for child in compound.childrenNamespaces:
            if child in state.compounds:
                state.compounds[child].parentGroup = compound.id
        for child in compound.childrenCompoundRefs:
            if child in state.compounds:
                state.compounds[child].parentGroup = compound.id

    # Strip name of parent symbols from names to get leaf names
    for _, compound in state.compounds.items():
        if not compound.parent or compound.kind in ['file', 'page', 'group']:
            compound.leaf_name = compound.name
            continue

        # Extract leaf namespace name from symbol name, take just everything
        # after the last ::, as the parent names may have intermediate inline
        # namespaces removed since 1.9.0 and https://github.com/doxygen/doxygen/commit/4372054e0b7af9c0cd1c1390859d8fef3581d8bb
        # The full name is reconstructed in a second step below.
        if compound.kind == 'namespace':
            compound.leaf_name = compound.name.rpartition('::')[2]

        # Strip parent namespace/class from symbol name
        elif compound.kind in ['struct', 'class', 'union']:
            prefix = state.compounds[compound.parent].name + '::'
            # assert compound.name.startswith(prefix), "Compound name `%s` does not start with `%s`" % (compound.name, prefix)
            if compound.name.startswith(prefix):
                compound.leaf_name = compound.name[len(prefix):]
            else:
                compound.leaf_name = compound.name

        # Strip parent dir from dir name
        elif compound.kind == 'dir':
            prefix = state.compounds[compound.parent].name + '/'
            if compound.name.startswith(prefix):
                compound.leaf_name = compound.name[len(prefix):]
            else:
                logging.warning("{}: potential issue: the parent of {}/ is {} which is not a prefix, you may want to enable FULL_PATH_NAMES together with STRIP_FROM_PATH and STRIP_FROM_INC_PATH to preserve filesystem hierarchy".format(state.current, compound.name, prefix))
                compound.leaf_name = compound.name

        # Other compounds are not in any index pages or breadcrumb, so leaf
        # name not needed

    # Now that we have leaf names for all namespaces made above, reconstruct
    # full names from them. FFS, so much extra code just to undo this crap.
    for _, compound in state.compounds.items():
        if not compound.kind == 'namespace':
            continue
        compound.name = compound.leaf_name
        parent = compound.parent
        while parent:
            compound_parent = state.compounds[parent]
            compound.name = compound_parent.leaf_name + '::' + compound.name
            parent = compound_parent.parent

    # Build reverse header name to ID mapping for #include information, unless
    # it's explicitly disabled. Doxygen doesn't provide full path for files so
    # we need to combine that ourselves. Ugh. (Yes, I know SHOW_INCLUDE_FILES
    # is meant to be for "a list of the files that are included by a file in
    # the documentation of that file" but that kind of information is so
    # glaringly useless in every imaginable way so I'm reusing it for something
    # saner.)
    if state.doxyfile['SHOW_INCLUDE_FILES']:
        for _, compound in state.compounds.items():
            if not compound.kind == 'file': continue

            # Gather parent compounds
            path_reverse = [compound.id]
            while path_reverse[-1] in state.compounds and state.compounds[path_reverse[-1]].parent:
                path_reverse += [state.compounds[path_reverse[-1]].parent]

            # Fill breadcrumb with leaf names and URLs
            include = []
            for i in reversed(path_reverse):
                # TODO the escaping / unescaping is a mess, fix that
                include += [html.unescape(state.compounds[i].leaf_name)]

            state.includes['/'.join(include)] = compound.id

    # Resolve navbar links that are just an ID
    def resolve_link(html_, title, url, id):
        if not html_ and not title and not url:
            assert id in state.compounds, "Navbar references {} which wasn't found".format(id)
            found = state.compounds[id]
            title, url = found.name, found.url
        return html_, title, url, id
    for var in 'LINKS_NAVBAR1', 'LINKS_NAVBAR2':
        links = []
        for html_, title, url, id, sub in state.config[var]:
            html_, title, url, id = resolve_link(html_, title, url, id)
            sublinks = []
            for i in sub:
                sublinks += [resolve_link(*i)]
            links += [(html_, title, url, id, sublinks)]
        state.config[var] = links

    for compound_id, compound in state.compounds.items():
        output = os.path.join(
            os.path.join(state.basedir, state.doxyfile['OUTPUT_DIRECTORY'], state.doxyfile['HTML_OUTPUT']), compound_id + '_meta_postprocessed.json')
        with open(output, "w", encoding="utf8") as f:
            json.dump(compound, f, cls=MappingProxyEncoder, indent=2)


def build_search_data(state: State, merge_subtrees=True, add_lookahead_barriers=True, merge_prefixes=True) -> bytearray:
    trie = Trie()
    map = ResultMap()

    strip_tags_re = re.compile('<.*?>')
    def strip_tags(text):
        return strip_tags_re.sub('', text)

    symbol_count = 0
    for result in state.search:
        # Decide on prefix joiner. Defines are among the :: ones as well,
        # because we need to add the function macros twice -- but they have no
        # prefix, so it's okay.
        if EntryType(result.flags.type) in [EntryType.NAMESPACE, EntryType.CLASS, EntryType.STRUCT, EntryType.UNION, EntryType.TYPEDEF, EntryType.FUNC, EntryType.VAR, EntryType.ENUM, EntryType.ENUM_VALUE, EntryType.DEFINE]:
            joiner = '::'
        elif EntryType(result.flags.type) in [EntryType.DIR, EntryType.FILE]:
            joiner = '/'
        elif EntryType(result.flags.type) in [EntryType.PAGE, EntryType.GROUP]:
            joiner = ' » '
        else:
            assert False # pragma: no cover

        # Handle function arguments
        name_with_args = result.name
        name = result.name
        suffix_length = 0
        if hasattr(result, 'params') and result.params is not None:
            # Some very heavily templated function parameters might cause the
            # suffix_length to exceed 256, which won't fit into the serialized
            # search data. However that *also* won't fit in the search result
            # list so there's no point in storing so much. Truncate it to 48
            # chars which should fit the full function name in the list in most
            # cases, yet be still long enough to be able to distinguish
            # particular overloads.
            # TODO: the suffix_length has to be calculated on UTF-8 and I
            # am (un)escaping a lot back and forth here -- needs to be
            # cleaned up
            params = html.unescape(strip_tags(', '.join(result.params)))
            if len(params) > 49:
                params = params[:48] + '…'
            name_with_args += '(' + html.escape(params) + ')'
            suffix_length += len(params.encode('utf-8')) + 2
        if hasattr(result, 'suffix') and result.suffix:
            name_with_args += result.suffix
            # TODO: escape elsewhere so i don't have to unescape here
            suffix_length += len(html.unescape(result.suffix))

        # TODO: escape elsewhere so i don't have to unescape here
        index = map.add(html.unescape(joiner.join(result.prefix + [name_with_args])), result.url, suffix_length=suffix_length, flags=result.flags)

        # Add functions and function macros the second time with () appended,
        # everything is the same except for suffix length which is 2 chars
        # shorter
        if hasattr(result, 'params') and result.params is not None:
            index_args = map.add(html.unescape(joiner.join(result.prefix + [name_with_args])), result.url,
                suffix_length=suffix_length - 2, flags=result.flags)

        # Add the result multiple times with all possible prefixes
        prefixed_name = result.prefix + [name]
        for i in range(len(prefixed_name)):
            lookahead_barriers = []
            name = ''
            for j in prefixed_name[i:]:
                if name:
                    lookahead_barriers += [len(name)]
                    name += joiner
                name += html.unescape(j)
            trie.insert(name.lower(), index, lookahead_barriers=lookahead_barriers if add_lookahead_barriers else [])

            # Add functions and function macros the second time with ()
            # appended, referencing the other result that expects () appended.
            # The lookahead barrier is at the ( character to avoid the result
            # being shown twice.
            if hasattr(result, 'params') and result.params is not None:
                trie.insert(name.lower() + '()', index_args, lookahead_barriers=lookahead_barriers + [len(name)] if add_lookahead_barriers else [])

        # Add keyword aliases for this symbol
        for search, title, suffix_length in result.keywords:
            if not title: title = search
            keyword_index = map.add(title, '', alias=index, suffix_length=suffix_length)
            trie.insert(search.lower(), keyword_index)

        # Add this symbol and all its aliases to total symbol count
        symbol_count += len(result.keywords) + 1

    # For each node in the trie sort the results so the found items have sane
    # order by default
    trie.sort(map)

    return serialize_search_data(Serializer(file_offset_bytes=state.config['SEARCH_FILE_OFFSET_BYTES'], result_id_bytes=state.config['SEARCH_RESULT_ID_BYTES'], name_size_bytes=state.config['SEARCH_NAME_SIZE_BYTES']), trie, map, search_type_map, symbol_count, merge_subtrees=merge_subtrees, merge_prefixes=merge_prefixes)


def parse_xml(state: State, xml: str):
    # Reset counter for unique math formulas
    latex2svgextra.counter = 0

    state.current = os.path.basename(xml)

    # All these early returns were logged in extract_metadata() already, no
    # need to print the same warnings/errors twice. Keep the two consistent.
    if state.current == 'Doxyfile.xml':
        return

    logging.debug("Parsing {}".format(state.current))

    try:
        tree = ET.parse(xml)
    except ET.ParseError as e:
        return
    root = tree.getroot()
    if root.tag != 'doxygen':
        return
    compounddef: ET.Element = root[0]
    if compounddef.tag != 'compounddef':
        return
    # See extract_metadata() for why `in []` is used
    if compounddef.attrib.get('language', 'C++') not in ['C++']:
        return

    assert len([i for i in root]) == 1

    # Ignoring private structs/classes and unnamed namespaces
    if ((compounddef.attrib['kind'] in ['struct', 'class', 'union'] and compounddef.attrib['prot'] == 'private') or
        # Doxygen 1.9.7+ makes <compoundname> empty for anonymous namespaces,
        # earlier versions put a generated name with @ there. See
        # test_compound.Ignored for a corresponding test case. Similar
        # difference is with anonymous enums.
        # https://github.com/doxygen/doxygen/commit/a18e4c76ed6415893800c7d77a2f798614fb638b
        (compounddef.attrib['kind'] == 'namespace' and (compounddef.find('compoundname').text is None or '@' in compounddef.find('compoundname').text))):
        logging.debug("{}: only private things, skipping".format(state.current))
        return None

    # In order to show also undocumented members, go through all empty
    # <briefdescription>s and fill them with a generic text.
    if state.config['SHOW_UNDOCUMENTED']:
        _document_all_stuff(compounddef)

    # Ignoring compounds w/o any description, except for groups,
    # which are created explicitly. Pages are treated as having something
    # unless they're stupid. See the function for details.
    #
    # ElementTree deprecated the __bool__ conversion of Element, so I now have
    # to check that `briefdescription` / `detaileddescription` actually has any
    # children. Checking against None is not enough as it could be present but
    # be empty.
    if not len(compounddef.find('briefdescription')) and not len(compounddef.find('detaileddescription')) and not compounddef.attrib['kind'] == 'group' and (not compounddef.attrib['kind'] == 'page' or is_a_stupid_empty_markdown_page(compounddef)):
        logging.debug("{}: neither brief nor detailed description present, skipping".format(state.current))
        return None

    compound = Empty()
    compound.kind = compounddef.attrib['kind']
    compound.id = compounddef.attrib['id']
    # Compound name is page filename, so we have to use title there. The same
    # is for groups.
    compound.name = compounddef.find('title').text if compound.kind in ['page', 'group'] and compounddef.findtext('title') else compounddef.find('compoundname').text
    # Compound URL is ID, except for index page, where it is named "indexpage"
    # and so I have to override it back to "index". Can't use <compoundname>
    # for pages because that doesn't reflect CASE_SENSE_NAMES. THANKS DOXYGEN.
    # This is similar to compound.url handling in extract_metadata() above.
    compound.url_base = ('index' if compound.id == 'indexpage' else compound.id)
    compound.url = compound.url_base + '.html'
    # Save current compound URL for search data building and ID extraction,
    # save current URL prefix for extract_id_hash() (these are the same for
    # top-level desc, but usually not for definitions, as an enum can be both
    # in file docs and namespace docs, for example)
    state.current_compound_url = compound.url
    state.current_definition_url_base = compound.url_base
    compound.include = None
    compound.has_template_details = False
    compound.templates = None
    compound.brief = parse_desc(state, compounddef.find('briefdescription'))
    compound.description, templates, compound.sections, footer_navigation, example_navigation, search_keywords, compound.deprecated, compound.since = parse_toplevel_desc(state, compounddef.find('detaileddescription'))
    compound.example_navigation = None
    compound.footer_navigation = None
    compound.topics = []
    compound.dirs = []
    compound.files = []
    compound.namespaces = []
    compound.classes = []
    compound.base_classes = []
    compound.derived_classes = []
    compound.enums = []
    compound.typedefs = []
    compound.funcs = []
    compound.vars = []
    compound.defines = []
    compound.public_types = []
    compound.public_static_funcs = []
    compound.typeless_funcs = []
    compound.public_funcs = []
    compound.signals = []
    compound.public_slots = []
    compound.public_static_vars = []
    compound.public_vars = []
    compound.protected_types = []
    compound.protected_static_funcs = []
    compound.protected_funcs = []
    compound.protected_slots = []
    compound.protected_static_vars = []
    compound.protected_vars = []
    compound.private_funcs = []
    compound.private_slots = []
    compound.related = []
    compound.friend_funcs = []
    compound.groups = []
    compound.has_enum_details = False
    compound.has_typedef_details = False
    compound.has_func_details = False
    compound.has_var_details = False
    compound.has_define_details = False

    logging.debug(f"  Parsing {compound.kind} in {state.current}")

    # Build breadcrumb. Breadcrumb for example pages is built after everything
    # is parsed.
    if compound.kind in ['namespace', 'group', 'struct', 'class', 'union', 'file', 'dir', 'page']:
        # Gather parent compounds
        path_reverse = [compound.id]
        while path_reverse[-1] in state.compounds and state.compounds[path_reverse[-1]].parent:
            path_reverse += [state.compounds[path_reverse[-1]].parent]

        # Fill breadcrumb with leaf names and URLs
        compound.breadcrumb = []
        for i in reversed(path_reverse):
            compound.breadcrumb += [(state.compounds[i].leaf_name, state.compounds[i].url)]

        # Gather parent groups
        path_reverse = [compound.id]
        while path_reverse[-1] in state.compounds and state.compounds[path_reverse[-1]].parentGroup:
            path_reverse += [state.compounds[path_reverse[-1]].parentGroup]

        # Fill breadcrumb with leaf names and URLs
        compound.breadcrumbGroup = []
        for i in reversed(path_reverse):
            compound.breadcrumbGroup += [(state.compounds[i].leaf_name, state.compounds[i].url)]

        # Save current prefix for search
        state.current_prefix = [name for name, _ in compound.breadcrumb]
    else:
        state.current_prefix = []

    # Inline namespaces
    if compound.kind == 'namespace':
        compound.is_inline = compounddef.attrib.get('inline') == 'yes'

    # Final classes
    if compound.kind in ['struct', 'class', 'union']:
        compound.is_final = compounddef.attrib.get('final') == 'yes'

    # Decide about the include file for this compound. Classes get it always,
    # namespaces without any class / group members too.
    state.current_kind = compound.kind
    if compound.kind in ['struct', 'class', 'union'] or (compound.kind == 'namespace' and compounddef.find('innerclass') is None and compounddef.find('innernamespace') is None and compounddef.find('sectiondef') is None):
        location_attribs = compounddef.find('location').attrib
        file = location_attribs['declfile'] if 'declfile' in location_attribs else location_attribs['file']

        # Classes, structs and unions allow supplying custom header file and a
        # custom include name, which *seems* to be present in the first
        # <includes> element of given compound. If that's the case, we use the
        # provided ID as the include link target and the name as the include
        # name. Otherwise the information is extracted from the <location> tag.
        # See test_compound.IncludesStripFromPath for a test case.
        #
        # Apparently, if STRIP_FROM_INC_PATH isn't set at all in the Doxyfile,
        # the damn thing does the worst possible and keeps just the leaf
        # filename there. Which is useless, so assume that if someone wants
        # to override include names, they also set STRIP_FROM_INC_PATH.
        #
        # Furthermore, if VERBATIM_HEADERS is disabled, the <includes> tag has
        # no refid, in which case we can't really make use of that either as
        # we won't know what to link to. Print at least a helpful warning in
        # that case.
        compound_includes = compounddef.find('includes')
        if state.doxyfile['STRIP_FROM_INC_PATH'] and compound.kind in ['struct', 'class', 'union'] and compound_includes is not None:
            if 'refid' in compound_includes.attrib:
                compound.include = make_class_include(state, compound_includes.attrib['refid'], compound_includes.text)
            else:
                actual_file = make_include_strip_from_path(file, state.doxyfile['STRIP_FROM_INC_PATH'])
                if compound_includes.text != actual_file:
                    logging.warning("{}: cannot use a custom include name <{}> with VERBATIM_HEADERS disabled, falling back to <{}>".format(state.current, compound_includes.text, actual_file))
                compound.include = make_include(state, file)
        else:
            compound.include = make_include(state, file)

        # Save include for current compound. Every enum/var/function/... parser
        # checks against it and resets to None in case the include differs for
        # given entry, meaning all entries need to have their own include
        # definition instead. That's then finally reflected in has_details of
        # each entry.
        #
        # If the class overrode the include location to something else above,
        # we *still* use the actual file from <location>, as otherwise an
        # include would get listed redundantly for all class members.
        state.current_include = file

    # Namespaces with members get a placeholder that gets filled from the
    # contents; but only if the namespace doesn't contain subnamespaces or
    # classes, in which case it would be misleading. It's done this way because
    # Doxygen sets namespace location to the first file it sees, which can be
    # a *.cpp file. In case the namespace doesn't have any members, it's set
    # above like with classes.
    #
    # Once current_include is filled for the first time in
    # parse_id_and_include(), every enum/var/function/... parser checks against
    # it and resets to None in case the include differs for given entry,
    # meaning all entries need to have their own include definition instead.
    # That's then finally reflected in has_details of each entry.
    elif compound.kind == 'namespace' and compounddef.find('innerclass') is None and compounddef.find('innernamespace') is None:
        state.current_include = ''

    # Files and dirs don't need it (it's implicit); and it makes no sense for
    # pages or topics (groups/modules).
    else:
        state.current_include = None

    if compound.kind == 'page':
        # Drop TOC for pages, if not requested
        if compounddef.find('tableofcontents') is None:
            compound.sections = []

        # Enable footer navigation, if requested
        if footer_navigation:
            up = state.compounds[compound.id].parent

            # Go through all parent children and find previous and next
            if up:
                up = state.compounds[up]

                prev = None
                next = None
                prev_child = None
                for child in up.children:
                    if child == compound.id:
                        if prev_child: prev = state.compounds[prev_child]
                    elif prev_child == compound.id:
                        next = state.compounds[child]
                        break

                    prev_child = child

                compound.footer_navigation = ((prev.url, prev.name) if prev else None,
                                              (up.url, up.name),
                                              (next.url, next.name) if next else None)

        if compound.brief:
            # Remove duplicated brief in pages. Doxygen sometimes adds a period
            # at the end, try without it also.
            # TODO: create follow-up to https://github.com/doxygen/doxygen/pull/624
            wrapped_brief = '<p>{}</p>'.format(compound.brief)
            if compound.description.startswith(wrapped_brief):
                compound.description = compound.description[len(wrapped_brief):]
            elif compound.brief[-1] == '.':
                wrapped_brief = '<p>{}</p>'.format(compound.brief[:-1])
                if compound.description.startswith(wrapped_brief):
                    compound.description = compound.description[len(wrapped_brief):]

    compounddef_child: ET.Element
    for compounddef_child in compounddef:
        # logging.debug(f"  Parsing {compounddef_child.tag} ({compounddef_child.attrib['kind'] if 'kind' in compounddef_child.attrib.keys() else ""}) within {compound.name} ({compound.kind})")
        logging.debug(
            "    Parsing {} ({}) within {} ({}) in {}".format(
                compounddef_child.tag.strip(),
                (
                    compounddef_child.attrib['kind'].strip()
                    if 'kind' in compounddef_child.attrib.keys()
                    else ""
                ),
                compound.name.strip(),
                compound.kind.strip(),
                state.current,
            )
        )

        # Directory / file
        if compounddef_child.tag in ['innerdir', 'innerfile']:
            id = compounddef_child.attrib['refid']

            # Add it only if we have documentation for it
            if id in state.compounds and state.compounds[id].has_details:
                file = state.compounds[id]

                f = Empty()
                f.url = file.url
                f.name = file.leaf_name
                f.brief = file.brief
                f.deprecated = file.deprecated
                f.since = file.since

                if compounddef_child.tag == 'innerdir':
                    compound.dirs += [f]
                else:
                    assert compounddef_child.tag == 'innerfile'
                    compound.files += [f]

        # Namespace / class
        elif compounddef_child.tag in ['innernamespace', 'innerclass']:
            id = compounddef_child.attrib['refid']

            # Add it only if it's not private and we have documentation for it
            if (compounddef_child.tag != 'innerclass' or not compounddef_child.attrib['prot'] == 'private') and id in state.compounds and state.compounds[id].has_details:
                symbol = state.compounds[id]

                if compounddef_child.tag == 'innernamespace':
                    namespace = Empty()
                    namespace.url = symbol.url
                    # Use the full name if this is a file or group (where the
                    # hierarchy isn't implicit like with namespace or class)
                    namespace.name = symbol.leaf_name if compound.kind == 'namespace' else symbol.name
                    namespace.brief = symbol.brief
                    namespace.deprecated = symbol.deprecated
                    namespace.since = symbol.since
                    namespace.is_inline = compounddef_child.attrib.get('inline') == 'yes'

                    # Children of inline namespaces get listed also in their
                    # parents as of 1.9.0 and https://github.com/doxygen/doxygen/commit/4372054e0b7af9c0cd1c1390859d8fef3581d8bb
                    # So e.g. if Bar is inline, Foo::Bar::Baz gets shortened to
                    # Foo::Baz, and listed as <innernamespace> of both Foo and
                    # Foo::Bar. Compare their IDs (because they don't get
                    # shortened) and add the namespace only if it's a direct
                    # descendant. Same is done in extract_metadata() above. See
                    # test_compound.InlineNamespace for a matching test case.
                    #
                    # Note that file / group compounds can also contain
                    # <innernamespace>. Those should list all namespaces
                    # always.
                    if compound.kind != 'namespace' or compounddef_child.attrib['refid'].rpartition('_1_1')[0] == compound.id:
                        compound.namespaces += [namespace]

                else:
                    assert compounddef_child.tag == 'innerclass'

                    class_ = Empty()
                    class_.kind = symbol.kind
                    class_.url = symbol.url
                    # Use the full name if this is a file or group (where the
                    # hierarchy isn't implicit like with namespace or class)
                    class_.name = symbol.leaf_name if compound.kind in ['namespace', 'class', 'struct', 'union'] else symbol.name
                    class_.brief = symbol.brief
                    class_.deprecated = symbol.deprecated
                    class_.since = symbol.since
                    class_.templates = symbol.templates

                    # Put classes into the public/protected section for
                    # inner classes
                    if compound.kind in ['class', 'struct', 'union']:
                        if compounddef_child.attrib['prot'] == 'public':
                            compound.public_types += [('class', class_)]
                        else:
                            assert compounddef_child.attrib['prot'] == 'protected'
                            compound.protected_types += [('class', class_)]
                    else:
                        assert compound.kind in ['namespace', 'group', 'file']
                        compound.classes += [class_]

        # Base class (if it links to anywhere)
        elif compounddef_child.tag == 'basecompoundref':
            assert compound.kind in ['class', 'struct', 'union']

            if 'refid' in compounddef_child.attrib:
                id = compounddef_child.attrib['refid']

                # Add it only if it's not private and we have documentation for it
                if not compounddef_child.attrib['prot'] == 'private' and id in state.compounds and state.compounds[id].has_details:
                    symbol = state.compounds[id]

                    # Strip parent if the base class has the same parent as
                    # this class. Can't just use symbol.leaf_name vs
                    # symbol.name because the <basecompoundref> can contain
                    # template information.
                    symbol_name = fix_type_spacing(html.escape(compounddef_child.text))
                    if state.compounds[compound.id].parent and symbol.parent and symbol.parent.startswith(state.compounds[compound.id].parent):
                        parent_name = state.compounds[symbol.parent].name + '::'
                        if symbol_name.startswith(parent_name):
                            symbol_name = symbol_name[len(parent_name):]

                    class_ = Empty()
                    class_.kind = symbol.kind
                    class_.url = symbol.url
                    class_.name = symbol_name
                    class_.brief = symbol.brief
                    class_.templates = symbol.templates
                    class_.deprecated = symbol.deprecated
                    class_.since = symbol.since
                    class_.is_protected = compounddef_child.attrib['prot'] == 'protected'
                    class_.is_virtual = compounddef_child.attrib['virt'] == 'virtual'

                    compound.base_classes += [class_]

        # Derived class (if it links to anywhere)
        elif compounddef_child.tag == 'derivedcompoundref':
            assert compound.kind in ['class', 'struct', 'union']

            if 'refid' in compounddef_child.attrib:
                id = compounddef_child.attrib['refid']

                # Add it only if it's not private and we have documentation for it
                if not compounddef_child.attrib['prot'] == 'private' and id in state.compounds and state.compounds[id].has_details:
                    symbol = state.compounds[id]

                    class_ = Empty()
                    class_.kind = symbol.kind
                    class_.url = symbol.url
                    # Use only the leaf name if the derived class has the same
                    # parent as this class
                    class_.name = symbol.leaf_name if state.compounds[compound.id].parent and symbol.parent and symbol.parent.startswith(state.compounds[compound.id].parent) else symbol.name
                    class_.brief = symbol.brief
                    class_.templates = symbol.templates
                    class_.deprecated = symbol.deprecated
                    class_.since = symbol.since
                    class_.is_virtual = compounddef_child.attrib['virt'] == 'virtual'
                    class_.is_final = symbol.is_final

                    compound.derived_classes += [class_]

        # Topic Groups (*not* member group)
        # These are called 'topics' in the Doxygen grouping documentation: https://www.doxygen.nl/manual/grouping.html
        # These are defined with \ingroup, \defgroup, \addtogroup, and \weakgroup
        elif compounddef_child.tag == 'innergroup':
            assert compound.kind == 'group'

            group = state.compounds[compounddef_child.attrib['refid']]
            g = Empty()
            g.url = group.url
            g.name = group.leaf_name
            g.brief = group.brief
            g.deprecated = group.deprecated
            g.since = group.since
            compound.topics += [g]

        # Other, grouped in sections
        elif compounddef_child.tag == 'sectiondef':
            # If grouping is used in the documentation, Doxygen 1.9.7+ no
            # longer puts the whole <memberdef> info into file and namespace
            # docs, but instead only <member> references, forcing the parsers
            # to look for the identifier in other XML files.
            #
            # The reason for this, as discussed in the linked PR, is because
            # some random downstream project failed due to encountering
            # duplicate IDs (which are there for file/namespace members also,
            # by the way! or for related members!!). And Doxygen maintainer
            # VERY HELPFULLY OFFERED TO CRIPPLE THE XML OUTPUT FOR EVERYONE
            # ELSE just to fix that damn thing. Once I calm down I may try to
            # convince them to revert this insanity, until then enjoy the
            # crappy output.
            #
            # Also, yes, it may happen that there are combined <memberdef> and
            # <member> children. But handling that means adding the same damn
            # piece of code, or some dumb filtering, to all branches below,
            # just to counter a dumb decision. Nope. Nononono.
            is_stupid = False
            for memberdef in compounddef_child:
                if memberdef.tag == 'member':
                    logging.info("{}: sorry, the output will not list file / namespace {} members due to https://github.com/doxygen/doxygen/issues/8790. Parsing of non-self-contained XML not implemented.".format(state.current, compounddef_child.attrib['kind']))
                    sectiondef_header = compounddef_child.find('header').text if compounddef_child.find('header') is not None else memberdef.find('name').text
                    member_name = memberdef.find('name').text
                    logging.info("{}: Reference to {} inside {} dropped, find it at {}".format(state.current, member_name.strip(), sectiondef_header.strip(), memberdef.attrib['refid']))
                    is_stupid = True
                    break
            if is_stupid:
                continue

            if compounddef_child.attrib['kind'] == 'enum':  # enum section
                for memberdef in compounddef_child:
                    enum = parse_enum(state, memberdef)
                    if enum:
                        compound.enums += [enum]
                        if enum.has_details: compound.has_enum_details = True

            elif compounddef_child.attrib['kind'] == 'typedef':  # typedef section
                for memberdef in compounddef_child:
                    typedef = parse_typedef(state, memberdef)
                    if typedef:
                        compound.typedefs += [typedef]
                        if typedef.has_details: compound.has_typedef_details = True

            elif compounddef_child.attrib['kind'] == 'func':  # func section
                for memberdef in compounddef_child:
                    func = parse_func(state, memberdef)
                    if func:
                        compound.funcs += [func]
                        if func.has_details: compound.has_func_details = True

            elif compounddef_child.attrib['kind'] == 'var':  # var section
                for memberdef in compounddef_child:
                    var = parse_var(state, memberdef)
                    if var:
                        compound.vars += [var]
                        if var.has_details: compound.has_var_details = True

            elif compounddef_child.attrib['kind'] == 'define':  # define section
                for memberdef in compounddef_child:
                    define = parse_define(state, memberdef)
                    if define:
                        compound.defines += [define]
                        if define.has_details: compound.has_define_details = True

            elif compounddef_child.attrib['kind'] == 'public-type':  # public-type section
                for memberdef in compounddef_child:
                    if memberdef.attrib['kind'] == 'enum':  # enum within public-type section
                        member = parse_enum(state, memberdef)
                        if member and member.has_details: compound.has_enum_details = True
                    else:
                        assert memberdef.attrib['kind'] == 'typedef'
                        member = parse_typedef(state, memberdef)
                        if member and member.has_details: compound.has_typedef_details = True

                    if member: compound.public_types += [(memberdef.attrib['kind'], member)]

            elif compounddef_child.attrib['kind'] == 'public-static-func':  # public-static-func section
                for memberdef in compounddef_child:
                    func = parse_func(state, memberdef)
                    if func:
                        compound.public_static_funcs += [func]
                        if func.has_details: compound.has_func_details = True

            elif compounddef_child.attrib['kind'] == 'public-func':  # public-func section
                for memberdef in compounddef_child:
                    func = parse_func(state, memberdef)
                    if func:
                        if func.type:
                            compound.public_funcs += [func]
                        else:
                            compound.typeless_funcs += [func]
                        if func.has_details: compound.has_func_details = True

            elif compounddef_child.attrib['kind'] == 'signal':  # signal section
                for memberdef in compounddef_child:
                    func = parse_func(state, memberdef)
                    if func:
                        compound.signals += [func]
                        if func.has_details: compound.has_func_details = True

            elif compounddef_child.attrib['kind'] == 'public-slot':  # public-slot section
                for memberdef in compounddef_child:
                    func = parse_func(state, memberdef)
                    if func:
                        compound.public_slots += [func]
                        if func.has_details: compound.has_func_details = True

            elif compounddef_child.attrib['kind'] == 'public-static-attrib':  # public-static-attrib section
                for memberdef in compounddef_child:
                    var = parse_var(state, memberdef)
                    if var:
                        compound.public_static_vars += [var]
                        if var.has_details: compound.has_var_details = True

            elif compounddef_child.attrib['kind'] == 'public-attrib':  # public-attrib section
                for memberdef in compounddef_child:
                    var = parse_var(state, memberdef)
                    if var:
                        compound.public_vars += [var]
                        if var.has_details: compound.has_var_details = True

            elif compounddef_child.attrib['kind'] == 'protected-type':  # protected-type section
                for memberdef in compounddef_child:
                    if memberdef.attrib['kind'] == 'enum':  # enum within protected-type section
                        member = parse_enum(state, memberdef)
                        if member and member.has_details: compound.has_enum_details = True
                    else:
                        assert memberdef.attrib['kind'] == 'typedef'
                        member = parse_typedef(state, memberdef)
                        if member and member.has_details: compound.has_typedef_details = True

                    if member: compound.protected_types += [(memberdef.attrib['kind'], member)]

            elif compounddef_child.attrib['kind'] == 'protected-static-func':  # protected-static-func section
                for memberdef in compounddef_child:
                    func = parse_func(state, memberdef)
                    if func:
                        compound.protected_static_funcs += [func]
                        if func.has_details: compound.has_func_details = True

            elif compounddef_child.attrib['kind'] == 'protected-func':  # protected-func section
                for memberdef in compounddef_child:
                    func = parse_func(state, memberdef)
                    if func:
                        if func.type:
                            compound.protected_funcs += [func]
                        else:
                            compound.typeless_funcs += [func]
                        if func.has_details: compound.has_func_details = True

            elif compounddef_child.attrib['kind'] == 'protected-slot':  # protected-slot section
                for memberdef in compounddef_child:
                    func = parse_func(state, memberdef)
                    if func:
                        compound.protected_slots += [func]
                        if func.has_details: compound.has_func_details = True

            elif compounddef_child.attrib['kind'] == 'protected-static-attrib':  # protected-static-attrib section
                for memberdef in compounddef_child:
                    var = parse_var(state, memberdef)
                    if var:
                        compound.protected_static_vars += [var]
                        if var.has_details: compound.has_var_details = True

            elif compounddef_child.attrib['kind'] == 'protected-attrib':  # protected-attrib section
                for memberdef in compounddef_child:
                    var = parse_var(state, memberdef)
                    if var:
                        compound.protected_vars += [var]
                        if var.has_details: compound.has_var_details = True

            elif compounddef_child.attrib['kind'] in ['private-func', 'private-slot']:
                # Gather only private functions that are virtual and
                # documented
                for memberdef in compounddef_child:
                    if memberdef.attrib['virt'] == 'non-virtual' or (not memberdef.find('briefdescription').text and not memberdef.find('detaileddescription').text):
                        assert True # coverage.py can't handle continue
                        continue # pragma: no cover

                    func = parse_func(state, memberdef)
                    if func:
                        if compounddef_child.attrib['kind'] == 'private-slot':
                            compound.private_slots += [func]
                        else:
                            compound.private_funcs += [func]
                        if func.has_details: compound.has_func_details = True

            elif compounddef_child.attrib['kind'] == 'related':  # related section
                for memberdef in compounddef_child:
                    if memberdef.attrib['kind'] == 'enum':  # enum within related section
                        enum = parse_enum(state, memberdef)
                        if enum:
                            compound.related += [('enum', enum)]
                            if enum.has_details: compound.has_enum_details = True
                    elif memberdef.attrib['kind'] == 'typedef':  # typedef within related section
                        typedef = parse_typedef(state, memberdef)
                        if typedef:
                            compound.related += [('typedef', typedef)]
                            if typedef.has_details: compound.has_typedef_details = True
                    elif memberdef.attrib['kind'] == 'function':  # function within related section
                        func = parse_func(state, memberdef)
                        if func:
                            compound.related += [('func', func)]
                            if func.has_details: compound.has_func_details = True
                    elif memberdef.attrib['kind'] == 'variable':  # variable within related section
                        var = parse_var(state, memberdef)
                        if var:
                            compound.related += [('var', var)]
                            if var.has_details: compound.has_var_details = True
                    elif memberdef.attrib['kind'] == 'define':  # define within related section
                        define = parse_define(state, memberdef)
                        if define:
                            compound.related += [('define', define)]
                            if define.has_details: compound.has_define_details = True
                    else: # pragma: no cover
                        logging.warning("{}: unknown related <memberdef> kind {}".format(state.current, memberdef.attrib['kind']))

            elif compounddef_child.attrib['kind'] == 'friend':  # friend section
                for memberdef in compounddef_child:
                    # Ignore friend classes. This does not ignore friend
                    # classes written as `friend Foo;`, those are parsed as
                    # variables (ugh). Since Doxygen 1.9 the `friend ` prefix
                    # is omitted.
                    if memberdef.find('type').text in ['class', 'struct', 'union', 'friend class', 'friend struct', 'friend union']:
                        # Print a warning in case these are documented
                        if (''.join(memberdef.find('briefdescription').itertext()).strip() or ''.join(memberdef.find('detaileddescription').itertext()).strip()):
                            logging.warning("{}: doxygen is unable to cross-link {}, ignoring, sorry".format(state.current, memberdef.find('definition').text))
                    # Only friend functions left, hopefully, parse as a func
                    else:
                        func = parse_func(state, memberdef)
                        if func:
                            compound.friend_funcs += [func]
                            if func.has_details: compound.has_func_details = True

            # user defined groupings
            # These are called 'member groups' in the Doxygen grouping documentation: https://www.doxygen.nl/manual/grouping.html
            # these are defined with @{..@} but no @ingroup or @defgroup
            # these groupings aren't even required to have a name
            elif compounddef_child.attrib['kind'] == 'user-defined':  # user-defined section (member group)
                list = []
                member_list = []
                memberdef_list = []

                memberdef: ET.Element
                for memberdef in compounddef_child.findall('memberdef'):
                    logging.debug(
                        f"Parsing {memberdef.attrib['kind']} member of user-defined group: "
                    )
                    if memberdef.attrib['kind'] == 'enum':  # enum within user-defined section/group
                        enum = parse_enum(state, memberdef)
                        if enum:
                            memberdef_list += [('enum', enum)]
                            if enum.has_details: compound.has_enum_details = True
                    elif memberdef.attrib['kind'] == 'typedef':  # typedef within user-defined section/group
                        typedef = parse_typedef(state, memberdef)
                        if typedef:
                            memberdef_list += [('typedef', typedef)]
                            if typedef.has_details: compound.has_typedef_details = True
                    elif memberdef.attrib['kind'] in ['function', 'signal', 'slot']:  # functions within user-defined section/group
                        # Gather only private functions that are virtual and
                        # documented
                        if memberdef.attrib['prot'] == 'private' and (memberdef.attrib['virt'] == 'non-virtual' or (not memberdef.find('briefdescription').text and not memberdef.find('detaileddescription').text)):
                            assert True # coverage.py can't handle continue
                            continue # pragma: no cover

                        func = parse_func(state, memberdef)
                        if func:
                            memberdef_list += [('func', func)]
                            if func.has_details: compound.has_func_details = True
                    elif memberdef.attrib['kind'] == 'variable':  # variable within user-defined section/group
                        var = parse_var(state, memberdef)
                        if var:
                            memberdef_list += [('var', var)]
                            if var.has_details: compound.has_var_details = True
                    elif memberdef.attrib['kind'] == 'define':  # define within user-defined section/group
                        define = parse_define(state, memberdef)
                        if define:
                            memberdef_list += [('define', define)]
                            if define.has_details: compound.has_define_details = True
                    elif memberdef.attrib['kind'] == 'friend':  # friend within user-defined section/group
                        # Ignore friend classes. This does not ignore friend
                        # classes written as `friend Foo;`, those are parsed as
                        # variables (ugh). Since Doxygen 1.9 the `friend `
                        # prefix is omitted.
                        if memberdef.find('type').text in ['class', 'struct', 'union', 'friend class', 'friend struct', 'friend union'] and (memberdef.find('briefdescription').text or memberdef.find('detaileddescription').text):
                            logging.warning("{}: doxygen is unable to cross-link {}, ignoring, sorry".format(state.current, memberdef.find('definition').text))
                        # Only friend functions left, hopefully, parse as a func
                        else:
                            func = parse_func(state, memberdef)
                            if func:
                                memberdef_list += [('func', func)]
                                if func.has_details: compound.has_func_details = True
                    else: # pragma: no cover
                        logging.warning("{}: unknown user-defined <memberdef> kind {}".format(state.current, memberdef.attrib['kind']))

                member: ET.Element
                for member in compounddef_child.findall('member'):
                    # These are the kinds supported within user-defined sections in the parse_xml function
                    if member.attrib['kind'] in ['enum', 'typedef', 'function', 'signal', 'slot', 'variable', 'define', 'friend']:
                        member_list += [member.attrib['refid']]
                    else: # pragma: no cover
                        logging.warning("{}: unknown referenced user-define group member kind {}".format(state.current, member.attrib['kind']))

                logging.debug("{}: member group found in user-defined section with {} reference members and {} full member-defs when parsing xml".format(state.current, len(member_list), len(memberdef_list)))

                # if we got only "members" defined elsewhere, reference should have already been processed into children, so do nothing here
                if len(member_list) and not len(memberdef_list):
                    logging.debug(
                        "{}: no memberdefs found within user-defined group {}".format(
                            state.current,
                            (
                                compounddef_child.find('header').text
                                if compounddef_child.find('header') is not None
                                else "un-named"
                            ),
                        )
                    )
                # if we only got complete memberdefs in this member group, add this group with its members to the compound
                elif not len(member_list) and len(memberdef_list):
                    header = compounddef_child.find('header')
                    if header is None:
                        logging.error("{}: member groups without @name are not supported, ignoring".format(state.current))
                    else:
                        group = Empty()
                        group.name = header.text
                        group.id = slugify(group.name)
                        group.description = parse_desc(state, compounddef_child.find('description'))
                        group.members = memberdef_list
                        compound.groups += [group]
                # if it's a mix.. (not sure if this is possible) we'll do nothing but throw a warning
                else:
                    logging.warning("Got a member group with both fully defined members and referenced members. The referenced members will be ignored!")

            elif compounddef_child.attrib['kind'] not in ['private-type',
                                                          'private-static-func',
                                                          'private-static-attrib',
                                                          'private-attrib']: # pragma: no cover
                logging.warning("{}: unknown <sectiondef> kind {}".format(state.current, compounddef_child.attrib['kind']))

        elif compounddef_child.tag == 'templateparamlist':
            compound.has_template_details, compound.templates = parse_template_params(state, compounddef_child, templates)

        elif (compounddef_child.tag not in ['compoundname',
                                            'briefdescription', # handled above
                                            'detaileddescription', # handled above
                                            'innerpage', # doesn't add anything to output
                                            'location', # handled above
                                            'includes',
                                            'includedby',
                                            'incdepgraph',
                                            'invincdepgraph',
                                            'inheritancegraph',
                                            'collaborationgraph',
                                            'listofallmembers',
                                            'tableofcontents'] and
            not (compounddef.attrib['kind'] in ['page', 'group'] and compounddef_child.tag == 'title')): # pragma: no cover
            logging.warning("{}: ignoring <{}> in <compounddef>".format(state.current, compounddef_child.tag))

    # Decide about the prefix (it may contain template parameters, so we
    # had to wait until everything is parsed)
    if compound.kind in ['namespace', 'struct', 'class', 'union']:
        # The name itself can contain templates (e.g. a specialized template),
        # so properly escape and fix spacing there as well
        compound.prefix_wbr = add_wbr(fix_type_spacing(html.escape(compound.name)))

        if compound.templates:
            compound.prefix_wbr += '&lt;'
            for index, t in enumerate(compound.templates):
                if index != 0: compound.prefix_wbr += ', '
                if t.name:
                    compound.prefix_wbr += t.name
                else:
                    compound.prefix_wbr += '_{}'.format(index+1)
            compound.prefix_wbr += '&gt;'

        compound.prefix_wbr += '::<wbr />'

    # Example pages
    if compound.kind == 'example':
        # Build breadcrumb navigation
        if example_navigation:
            if not compound.name.startswith(example_navigation[1]): # pragma: no cover
                logging.critical("{}: example filename is not prefixed with {}".format(state.current, example_navigation[1]))
                assert False

            prefix_length = len(example_navigation[1])

            path_reverse = [example_navigation[0]]
            while path_reverse[-1] in state.compounds and state.compounds[path_reverse[-1]].parent:
                path_reverse += [state.compounds[path_reverse[-1]].parent]

            # Fill breadcrumb with leaf names and URLs
            compound.breadcrumb = []
            for i in reversed(path_reverse):
                compound.breadcrumb += [(state.compounds[i].leaf_name, state.compounds[i].url)]

            # Add example filename as leaf item
            compound.breadcrumb += [(compound.name[prefix_length:], compound.id + '.html')]

            # Enable footer navigation, if requested
            if footer_navigation:
                up = state.compounds[example_navigation[0]]

                prev = None
                next = None
                prev_child = None
                for example in state.examples:
                    if example.id == compound.id:
                        if prev_child: prev = prev_child
                    elif prev_child and prev_child.id == compound.id:
                        if example.name.startswith(example_navigation[1]):
                            next = example
                        break

                    if example.name.startswith(example_navigation[1]):
                        prev_child = example

                compound.footer_navigation = ((prev.url, prev.name[prefix_length:]) if prev else None,
                                              (up.url, up.name),
                                              (next.url, next.name[prefix_length:]) if next else None)

        else:
            compound.breadcrumb = [(compound.name, compound.id + '.html')]

    # Special handling for compounds that might or might not have a common
    # #include (for all others the include info is either on a compound itself
    # or nowhere at all)
    if state.doxyfile['SHOW_INCLUDE_FILES'] and compound.kind in ['namespace', 'group']:
        # If we're in a namespace, its include info comes from inside
        if compound.kind == 'namespace' and state.current_include:
            compound.include = make_include(state, state.current_include)

        # If we discovered that entries of this compound don't have a common
        # #include (and the entry isn't just a reference to a definition in
        # some other page), flip on has_details of all entries and wipe the
        # compound include. Otherwise wipe the include information from
        # everywhere but the compound.
        if not state.current_include:
            compound.include = None
        for entry in compound.enums:
            if entry.include and not state.current_include and entry.base_url == compound.url:
                entry.has_details = True
                compound.has_enum_details = True
            else:
                entry.include = None
        for entry in compound.typedefs:
            if entry.include and not state.current_include and entry.base_url == compound.url:
                entry.has_details = True
                compound.has_typedef_details = True
            else:
                entry.include = None
        for entry in compound.funcs:
            if entry.include and not state.current_include and entry.base_url == compound.url:
                entry.has_details = True
                compound.has_func_details = True
            else:
                entry.include = None
        for entry in compound.vars:
            if entry.include and not state.current_include and entry.base_url == compound.url:
                entry.has_details = True
                compound.has_var_details = True
            else:
                entry.include = None
        for entry in compound.defines:
            if entry.include and not state.current_include and entry.base_url == compound.url:
                entry.has_details = True
                compound.has_define_details = True
            else:
                entry.include = None
        # Skipping public_types etc., as that is for classes which have a
        # global include anyway
        for group in compound.groups:
            for kind, entry in group.members:
                if entry.include and not state.current_include and entry.base_url == compound.url:
                    entry.has_details = True
                    setattr(compound, 'has_{}_details'.format(kind), True)
                else:
                    entry.include = None

    # Add the compound to search data, if it's documented
    #
    # ElementTree deprecated the __bool__ conversion of Element, so I now have
    # to check that `detaileddescription` actually has any children. Checking
    # against None is not enough as it could be present but be empty.
    # TODO: add example sources there? how?
    if not state.config['SEARCH_DISABLED'] and not compound.kind == 'example' and (compound.kind == 'group' or compound.brief or len(compounddef.find('detaileddescription'))):
        if compound.kind == 'namespace':
            kind = EntryType.NAMESPACE
        elif compound.kind == 'struct':
            kind = EntryType.STRUCT
        elif compound.kind == 'class':
            kind = EntryType.CLASS
        elif compound.kind == 'union':
            kind = EntryType.UNION
        elif compound.kind == 'dir':
            kind = EntryType.DIR
        elif compound.kind == 'file':
            kind = EntryType.FILE
        elif compound.kind == 'page':
            kind = EntryType.PAGE
        elif compound.kind == 'group':
            kind = EntryType.GROUP
        else:
            assert False  # pragma: no cover

        result = Empty()
        result.flags = ResultFlag.from_type(ResultFlag.DEPRECATED if compound.deprecated else ResultFlag(0), kind)
        result.url = compound.url
        result.prefix = state.current_prefix[:-1]
        result.name = state.current_prefix[-1]
        result.keywords = search_keywords
        state.search += [result]

    parsed = Empty()
    parsed.version = root.attrib['version']
    parsed.compound = compound
    return parsed


def parse_index_xml(state: State, xml):
    logging.debug("Parsing Index File {}".format(os.path.basename(xml)))

    tree = ET.parse(xml)
    root = tree.getroot()
    assert root.tag == 'doxygenindex'

    # Top-level symbols, files and pages. Separated to nestable (namespaces,
    # groups, dirs) and non-nestable so we have these listed first.
    top_level_namespaces = []
    top_level_classes = []
    top_level_dirs = []
    top_level_files = []
    top_level_pages = []
    top_level_topics = []

    # Non-top-level symbols, files and pages, assigned later
    orphans_nestable = {}
    orphan_pages = {}
    orphans = {}

    # Map of all entries
    entries = {}

    i: ET.Element
    for i in root:
        assert i.tag == 'compound'

        entry = Empty()
        entry.id = i.attrib['refid']

        # Ignore unknown / undocumented compounds
        if entry.id not in state.compounds or not state.compounds[entry.id].has_details:
            continue

        compound = state.compounds[entry.id]
        entry.kind = compound.kind
        entry.name = compound.leaf_name
        entry.url = compound.url
        entry.brief = compound.brief
        entry.children = []
        entry.deprecated = compound.deprecated
        entry.since = compound.since
        entry.has_nestable_children = False
        if compound.kind == 'namespace':
            entry.is_inline = compound.is_inline

            # As of 1.9.0 and https://github.com/doxygen/doxygen/commit/4372054e0b7af9c0cd1c1390859d8fef3581d8bb
            # children of inline namespaces are listed twice in index.xml, once
            # with their full name, and once with the intermediate inline
            # namespaces removed. Keep just the ones with full names, i.e.
            # where the name matches what was painstakingly reconstructed
            # in postprocess_state() before. I hate this fucking tool of a
            # tool.
            if compound.name != i.findtext('name'):
                continue

        if compound.kind in ['class', 'struct', 'union']:
            entry.is_final = compound.is_final
        # print("name:",compound.name, "\tkind:", compound.kind, "\tparents:", compound.parent)

        # If a top-level thing, put it directly into the list
        if not compound.parent:
            if compound.kind == 'namespace':
                top_level_namespaces += [entry]
            elif compound.kind == 'group':
                top_level_topics += [entry]
            elif compound.kind in ['class', 'struct', 'union']:
                top_level_classes += [entry]
            elif compound.kind == 'dir':
                top_level_dirs += [entry]
            elif compound.kind == 'file':
                top_level_files += [entry]
            else:
                assert compound.kind == 'page'
                # Ignore index page in page listing, add it later only if it
                # has children
                if entry.id != 'indexpage': top_level_pages += [entry]

        # Otherwise put it into orphan map
        else:
            if compound.kind in ['namespace', 'group', 'dir', 'class']:
                if not compound.parent in orphans_nestable:
                    orphans_nestable[compound.parent] = []
                orphans_nestable[compound.parent] += [entry]
            elif compound.kind == 'page':
                if not compound.parent in orphan_pages:
                    orphan_pages[compound.parent] = {}
                orphan_pages[compound.parent][entry.id] = entry
            else:
                assert compound.kind in ['struct', 'union', 'file']
                if not compound.parent in orphans:
                    orphans[compound.parent] = []
                orphans[compound.parent] += [entry]

        # Put it also in the global map so we can reference it later when
        # getting rid of orphans
        entries[entry.id] = entry

    # Structure containing top-level symbols, files and pages, nestable items
    # (namespaces, directories) first
    parsed = Empty()
    parsed.version = root.attrib['version']
    parsed.index = Empty()
    parsed.index.symbols = top_level_namespaces + top_level_classes
    parsed.index.files = top_level_dirs + top_level_files
    parsed.index.pages = top_level_pages
    parsed.index.topics = top_level_topics

    # Assign nestable children to their parents first, if the parents exist
    for parent, children in orphans_nestable.items():
        if not parent in entries: continue
        entries[parent].has_nestable_children = True
        entries[parent].children = children

    # Add child pages to their parent pages. The user-defined order matters, so
    # preserve it.
    for parent, children in orphan_pages.items():
        assert parent in entries
        compound = state.compounds[parent]
        for child in compound.children:
            entries[parent].children += [children[child]]

    # Add children to their parents, if the parents exist
    for parent, children in orphans.items():
        if parent in entries: entries[parent].children += children

    # Add the index page if it has children
    if 'indexpage' in entries and entries['indexpage'].children:
        parsed.index.pages = [entries['indexpage']] + parsed.index.pages

    return parsed


def parse_doxyfile(state: State, doxyfile, values = None):
    # Use top-level Doxyfile path as base, don't let it get overridden by
    # subsequently @INCLUDE'd Doxyfile
    if not state.basedir:
        state.basedir = os.path.dirname(doxyfile)

    logging.debug("Parsing configuration from {}".format(doxyfile))

    comment_re = re.compile(r"""^\s*(#.*)?$""")
    variable_re = re.compile(r"""^\s*(##!\s*)?(?P<key>[A-Z0-9_@]+)\s*=\s*(?P<quote>['"]?)(?P<value>.*)(?P=quote)\s*(?P<backslash>\\?)$""")
    variable_continuation_re = re.compile(r"""^\s*(##!\s*)?(?P<key>[A-Z_]+)\s*\+=\s*(?P<quote>['"]?)(?P<value>.*)(?P=quote)\s*(?P<backslash>\\?)$""")
    continuation_re = re.compile(r"""^\s*(##!\s*)?(?P<quote>['"]?)(?P<value>.*)(?P=quote)\s*(?P<backslash>\\?)$""")

    default_values = {
        'PROJECT_NAME': ['My Project'],
        'PROJECT_LOGO': [''],
        'OUTPUT_DIRECTORY': [''],
        'XML_OUTPUT': ['xml'],
        'HTML_OUTPUT': ['html'],
        'DOT_FONTNAME': ['Helvetica'],
        'DOT_FONTSIZE': ['10'],
        'SHOW_INCLUDE_FILES': ['YES'],
        'STRIP_FROM_PATH': [''],
        'STRIP_FROM_INC_PATH': [''],
    }

    # Defaults so we don't fail with minimal Doxyfiles and also that the
    # user-provided Doxygen can append to them. They are later converted to
    # string or kept as a list based on type, so all have to be a list of
    # strings now.
    #
    # If there are no `values`, it means this is a top-level call (not recursed
    # from Doxyfile @INCLUDEs). In that case (and only in that case) we
    # finalize the config values (such as expanding FAVICON or LINKS_NAVBAR).
    if not values:
        finalize = True
        values = copy.deepcopy(default_values)
    else:
        finalize = False

    def parse_value(var):
        if var.group('quote') in ['"', '\'']:
            out = [var.group('value')]
        else:
            out = var.group('value').split()

        if var.group('quote') and var.group('backslash') == '\\':
            backslash = True
        elif out and out[-1].endswith('\\'):
            backslash = True
            out[-1] = out[-1][:-1].rstrip()
        else:
            backslash = False

        return [i.replace('\\"', '"').replace('\\\'', '\'') for i in out], backslash

    with open(doxyfile, encoding='utf-8') as f:
        continued_line = None
        for line in f:
            line = line.strip()

            # Line continuation from before, append the line contents to it.
            # Needs to be before variable so variable-looking continuations
            # are not parsed as variables.
            if continued_line:
                var = continuation_re.match(line)
                value, backslash = parse_value(var)
                values[continued_line] += value
                if not backslash: continued_line = None
                continue

            # Variable
            var = variable_re.match(line)
            if var:
                key = var.group('key')
                value, backslash = parse_value(var)

                # Another file included, parse it
                if key == '@INCLUDE':
                    parse_doxyfile(state, os.path.join(os.path.dirname(doxyfile), ' '.join(value)), values)
                    assert not backslash
                else:
                    values[key] = value

                if backslash: continued_line = key
                continue

            # Variable, adding to existing
            var = variable_continuation_re.match(line)
            if var:
                key = var.group('key')
                if not key in values: values[key] = []
                value, backslash = parse_value(var)
                values[key] += value
                if backslash: continued_line = key

                # only because coverage.py can't handle continue
                continue # pragma: no cover

            # Ignore comments and empty lines. Comment also stops line
            # continuation. Has to be last because variables can be inside
            # comments.
            if comment_re.match(line):
                continued_line = None
                continue

            logging.warning("{}: unmatchable line {}".format(doxyfile, line)) # pragma: no cover

    # Some values are set to empty in the default-generated Doxyfile but they
    # shouldn't be empty. Delete the variable ín that case so it doesn't
    # override our defaults.
    for i in ['HTML_EXTRA_STYLESHEET']:
        if i in values and not values[i]: del values[i]

    # Parse recognized Doxyfile values with desired type. The second tuple
    # value denotes that the Doxyfile value is an alias to a value in conf.py,
    # in which case we'll save it there instead.
    for key, alias, type_ in [
        # Order roughly the same as in python.py default_config to keep those
        # two consistent
        ('PROJECT_NAME', None, str),
        ('PROJECT_NUMBER', None, str),
        ('PROJECT_BRIEF', None, str),
        ('PROJECT_LOGO', None, str),
        ('PROJECT_REPOSITORY', None, str),
        ('M_MAIN_PROJECT_URL', 'MAIN_PROJECT_URL', str),

        ('OUTPUT_DIRECTORY', None, str),
        ('HTML_OUTPUT', None, str),
        ('XML_OUTPUT', None, str),

        ('USE_MATHJAX', None, bool),
        ('MATHJAX_VERSION', None, str),
        ('MATHJAX_FORMAT', None, str),
        ('MATHJAX_RELPATH', None, str),
        ('MATHJAX_EXTENSIONS', None, str), # NOT SUPPORTED
        ('MATHJAX_CODEFILE', None, str),

        ('DOT_FONTNAME', None, str),
        ('DOT_FONTSIZE', None, int),

        ('CREATE_SUBDIRS', None, bool), # processing fails below if this is set
        ('JAVADOC_AUTOBRIEF', None, bool),
        ('QT_AUTOBRIEF', None, bool),
        ('INTERNAL_DOCS', None, bool),
        ('SHOW_INCLUDE_FILES', None, bool),
        ('TAGFILES', None, list),
        ('STRIP_FROM_PATH', None, list),
        ('STRIP_FROM_INC_PATH', None, list),

        ('M_THEME_COLOR', 'THEME_COLOR', str),
        ('M_FAVICON', 'FAVICON', str), # plus special handling below
        ('HTML_EXTRA_STYLESHEET', 'STYLESHEETS', list),
        ('HTML_EXTRA_FILES', 'EXTRA_FILES', list),
        # M_LINKS_NAVBAR1 and M_LINKS_NAVBAR2 have special handling below

        ('M_HTML_HEADER', 'HTML_HEADER', str),
        ('M_PAGE_HEADER', 'PAGE_HEADER', str),
        ('M_PAGE_FINE_PRINT', 'FINE_PRINT', str),

        ('M_CLASS_TREE_EXPAND_LEVELS', 'CLASS_INDEX_EXPAND_LEVELS', int),
        ('M_EXPAND_INNER_TYPES', 'CLASS_INDEX_EXPAND_INNER', bool),
        ('M_FILE_TREE_EXPAND_LEVELS', 'FILE_INDEX_EXPAND_LEVELS', int),

        ('M_SEARCH_DISABLED', 'SEARCH_DISABLED', bool),
        ('M_SEARCH_DOWNLOAD_BINARY', 'SEARCH_DOWNLOAD_BINARY', bool),
        ('M_SEARCH_FILENAME_PREFIX', 'SEARCH_FILENAME_PREFIX', str),
        ('M_SEARCH_RESULT_ID_BYTES', 'SEARCH_RESULT_ID_BYTES', int),
        ('M_SEARCH_FILE_OFFSET_BYTES', 'SEARCH_FILE_OFFSET_BYTES', int),
        ('M_SEARCH_NAME_SIZE_BYTES', 'SEARCH_NAME_SIZE_BYTES', int),
        ('M_SEARCH_HELP', 'SEARCH_HELP', str),
        ('M_SEARCH_BASE_URL', 'SEARCH_BASE_URL', str),
        ('M_SEARCH_EXTERNAL_URL', 'SEARCH_EXTERNAL_URL', str),

        ('M_SHOW_UNDOCUMENTED', 'SHOW_UNDOCUMENTED', bool),
        ('M_VERSION_LABELS', 'VERSION_LABELS', bool),

        ('M_MATH_CACHE_FILE', 'M_MATH_CACHE_FILE', str),
        ('M_MATH_RENDER_AS_CODE', 'M_MATH_RENDER_AS_CODE', bool),
    ]:
        if key not in values: continue

        if type_ is str:
            value = '\n'.join(values[key])
        elif type_ is int:
            value = int(' '.join(values[key]))
        elif type_ is bool:
            value = ' '.join(values[key]) == 'YES'
        elif type_ is list:
            value = [line for line in values[key] if line] # Drop empty lines
        else: # pragma: no cover
            assert False

        # if we have different information in this Doxyfile and what we've previously read and both are different from the default
        if (alias and alias in state.config.keys() and state.config[alias] != default_config[alias] and value != default_config[alias]) or (
                key in state.config.keys() and state.config[key] != default_config[key] and value != default_config[key]):
            # if we have lists combine them
            if type_ is list:
                logging.warning(f"Extending {alias} with {key} from {doxyfile}")
                state.config[alias].extend(value)
            else:
                # if it's not a list ignore it and issue a warning
                logging.warning(f"Ignoring {value} for {key} from {doxyfile} because {alias} has already been set to {state.config[alias]}")
        # if we have no information in this Doxyfile and a value was already set in the config, ignore the re-read default
        elif (alias and alias in state.config.keys() and value == default_config[alias]) or (
                key in state.config.keys() and value == default_config[key]):
            logging.debug(f"Ignoring default value for {key} ({alias}) from {doxyfile}.")
        # If there's nothing in the python file, just use the Doxyfile
        elif alias:
            state.config[alias] = value
        else:
            state.doxyfile[key] = value

    # Process M_LINKS_NAVBAR[12] into either (HTML, sublinks) or
    # (title, URL, ID, sublinks), with sublinks being either
    # (HTML) or (title, URL, ID). Those are then saved into LINKS_NAVBAR[12]
    # and processed further.
    predefined = {
        'pages': ("Pages", 'pages.html'),
        'namespaces': ("Namespaces", 'namespaces.html'),
        'topics': ("Topics", 'topics.html'),
        'annotated': ("Classes", 'annotated.html'),
        'files': ("Files", 'files.html'),
        'index': ("Main Page", 'index.html')
    }

    def extract_link(link):
        # If this is a HTML code, return it as a one-item tuple
        if link.startswith('<a'):
            return (link, )

        # If predefined, return those
        if link in predefined:
            return (predefined[link][0], link)

        # Otherwise keep the ID, which will be resolved later
        return None, link
    for key, alias in [
        ('M_LINKS_NAVBAR1', 'LINKS_NAVBAR1'),
        ('M_LINKS_NAVBAR2', 'LINKS_NAVBAR2')
    ]:
        if key not in values: continue

        navbar_links = []
        # Drop empty lines
        for i in [line for line in values[key] if line]:
            # Split the line into links. It's either single-word keywords or
            # HTML <a> elements. If it looks like a HTML, take everything until
            # the closing </a>, otherwise take everything until the next
            # whitespace.
            links = []
            while i:
                if i.startswith('<a'):
                    end = i.index('</a>') + 4
                    links += [i[0:end]]
                    i = i[end:].lstrip()
                else:
                    firstAndRest = i.split(None, 1)
                    if len(firstAndRest):
                        links += [firstAndRest[0]]
                        if len(firstAndRest) == 1:
                            break;
                    i = firstAndRest[1]

            sublinks = []
            for sublink in links[1:]:
                sublinks += [extract_link(sublink)]
            navbar_links += [extract_link(links[0]) + (sublinks, )]

        state.config[alias] = navbar_links

    # File paths extracted from <location file="loc"/> have already been
    # stripped with respect to the Doxygen STRIP_FROM_PATH option. However, the
    # make_include function needs to additionally strip any prefix present in
    # STRIP_FROM_INC_PATH if present.
    if state.doxyfile['STRIP_FROM_INC_PATH'] is not None:
        all_prefixes = state.doxyfile['STRIP_FROM_INC_PATH']
        # Add all the prefixes in STRIP_FROM_INC_PATH which have a common
        # prefix with STRIP_FROM_PATH
        for path_prefix in state.doxyfile['STRIP_FROM_PATH']:
            # Construct the list of non empty suffixes of STRIP_FROM_INC_PATH
            # for this STRIP_FROM_PATH prefix
            from_path_strip = list(filter(bool, map(lambda x: remove_path_prefix(x, path_prefix), state.doxyfile['STRIP_FROM_INC_PATH'])))
            all_prefixes += from_path_strip
        # Remove duplicates
        state.doxyfile['STRIP_FROM_INC_PATH'] = list(set(all_prefixes))

    # Below we finalize the config values, converting them to formats that are
    # easy to understand by the code / templates (but not easy to write from
    # the user PoV). If this is not a top-level call (but a recursed one from
    # @INCLUDE), we exit, to avoid finalizing everything multiple times.
    if not finalize: return

    # Convert the links from either (html, ) or (title, id) to a
    # (html, title, url, id) tuple so it's easier to process by the template.
    # The url is not known at this point and will be filled later in
    # postprocess_state().
    def expand_link(link):
        if len(link) == 1:
            return (link[0], None, None, None)
        else:
            logging.debug(link)
            assert len(link) == 2
            if link[1] in predefined:
                url = predefined[link[1]][1]
                if not link[0]: title = predefined[link[1]][0]
                else: title = link[0]
            else:
                title = None
                url = None
            return (None, title, url, link[1])
    for key in ('LINKS_NAVBAR1', 'LINKS_NAVBAR2'):
        links = []
        for i in state.config[key]:
            sublinks = []
            for subi in i[-1]:
                sublinks += [expand_link(subi)]
            links += [expand_link(i[:-1]) + (sublinks, )]
        state.config[key] = links

    # Guess MIME type of the favicon. It's supplied explicitly when coming from
    # a conf.py
    if 'FAVICON' in state.config and state.config['FAVICON']:
        state.config['FAVICON'] = (state.config['FAVICON'], mimetypes.guess_type(state.config['FAVICON'])[0])

    # Fail if this option is set
    if state.doxyfile.get('CREATE_SUBDIRS', False):
        logging.fatal("{}: CREATE_SUBDIRS is not supported, sorry. Disable it and try again.".format(doxyfile))
        raise NotImplementedError

default_index_pages = ['pages', 'files', 'namespaces', 'topics', 'annotated']
default_wildcard = '*.xml'
default_templates = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'templates/doxygen/')

def run(state: State, *, templates=default_templates, wildcard=default_wildcard, index_pages=default_index_pages, search_add_lookahead_barriers=True, search_merge_subtrees=True, search_merge_prefixes=True, sort_globbed_files=False):
    xml_input = os.path.join(state.basedir, state.doxyfile['OUTPUT_DIRECTORY'], state.doxyfile['XML_OUTPUT'])
    xml_files_metadata = [os.path.join(xml_input, f) for f in glob.glob(os.path.join(xml_input, "*.xml"))]
    xml_files = [os.path.join(xml_input, f) for f in glob.glob(os.path.join(xml_input, wildcard))]
    html_output = os.path.join(state.basedir, state.doxyfile['OUTPUT_DIRECTORY'], state.doxyfile['HTML_OUTPUT'])

    # If math rendering cache is not disabled, load the previous version. If
    # there is no cache, reset the cache to an empty state to avoid
    # order-dependent issues when testing
    math_cache_file = os.path.join(state.basedir, state.doxyfile['OUTPUT_DIRECTORY'], state.config['M_MATH_CACHE_FILE'])
    if not state.config['M_MATH_RENDER_AS_CODE'] and not state.doxyfile['USE_MATHJAX']:
        if state.config['M_MATH_CACHE_FILE'] and os.path.exists(math_cache_file):
            logging.debug("Unpickling latex2svg math cache file: {}".format(math_cache_file))
            latex2svgextra.unpickle_cache(math_cache_file)
        else:
            logging.debug("No latex2svg math cache to unpickle")
            latex2svgextra.unpickle_cache(None)

    # Configure graphviz/dot
    logging.debug("Configuring GraphViz (dot) with font {} size {}".format(state.doxyfile['DOT_FONTNAME'].strip(), state.doxyfile['DOT_FONTSIZE']))
    dot2svg.configure(state.doxyfile['DOT_FONTNAME'], state.doxyfile['DOT_FONTSIZE'])

    if sort_globbed_files:
        xml_files_metadata.sort()
        xml_files.sort()

    if not os.path.exists(html_output):
        os.makedirs(html_output)

    # If custom template dir was supplied, use the default template directory
    # as a fallback
    template_paths = [templates]
    if templates != default_templates: template_paths += [default_templates]
    env = Environment(loader=FileSystemLoader(template_paths),
                      trim_blocks=True, lstrip_blocks=True, enable_async=True)

    # Filter to return file basename or the full URL, if absolute
    def basename_or_url(path):
        if urllib.parse.urlparse(path).netloc: return path
        return os.path.basename(path)
    def rtrim(value): return value.rstrip()
    env.filters['rtrim'] = rtrim
    env.filters['basename_or_url'] = basename_or_url
    env.filters['urljoin'] = urllib.parse.urljoin

    # Do a pre-pass and gather:
    # - brief descriptions of all classes, namespaces, dirs and files because
    #   the brief desc is not part of the <inner*> tag
    # - template specifications of all classes so we can include that in the
    #   linking pages
    # - get URLs of namespace, class, file docs and pages so we can link to
    #   them from breadcrumb navigation
    file: str
    for file in xml_files_metadata:
        extract_metadata(state, file)

    postprocess_state(state)

    # output = os.path.join(html_output, "postProcessedState.dump")
    # with open(output, 'w', encoding="utf8") as f:
    #     print(state, file=f)

    output = os.path.join(html_output, "postProcessedState.json")
    with open(output, "w", encoding="utf8") as f:
        json.dump(state, f, cls=MappingProxyEncoder, indent=2)

    for file in xml_files:
        # print(file)
        if os.path.basename(file) == 'Doxyfile.xml':
            logging.debug("Skipping xml of doxyfile")

        elif os.path.basename(file) == 'index.xml':
            parsed = parse_index_xml(state, file)
            output = os.path.join(html_output, "index_parsed.json")
            with open(output, "w", encoding="utf8") as f:
                json.dump(parsed, f, cls=MappingProxyEncoder, indent=2)

            for i in index_pages:
                file = '{}.html'.format(i)

                template = env.get_template(file)
                rendered = template.render(index=parsed.index,
                    DOXYGEN_VERSION=parsed.version,
                    FILENAME=file,
                    SEARCHDATA_FORMAT_VERSION=searchdata_format_version,
                    # TODO: whitelist only what matters from doxyfile
                    **state.doxyfile, **state.config)

                output = os.path.join(html_output, file)
                with open(output, 'wb') as f:
                    f.write(rendered.encode('utf-8'))
                    # Add back a trailing newline so we don't need to bother
                    # with patching test files to include a trailing newline to
                    # make Git happy. Can't use keep_trailing_newline because
                    # that'd add it also for nested templates :( The rendered
                    # file should never contain a trailing newline on its own.
                    assert not rendered.endswith('\n')
                    f.write(b'\n')
        else:
            parsed = parse_xml(state, file)
            if not parsed: continue

            output = os.path.join(
                html_output, os.path.basename(file).replace(".xml", ".json")
            )
            with open(output, "w", encoding="utf8") as f:
                json.dump(parsed, f, cls=MappingProxyEncoder, indent=2)

            # print(parsed.compound.kind, parsed.compound.name,parsed.compound.id)
            # if parsed.compound.kind == 'group' and parsed.compound.id.startswith('group__sensor__'):
            #     template = env.get_template('sensor.html')
            # elif parsed.compound.kind == 'group' and parsed.compound.id.startswith('group__modem__'):
            #     template = env.get_template('modem.html')
            # else:
            #     template = env.get_template('{}.html'.format(parsed.compound.kind))
            template = env.get_template('{}.html'.format(parsed.compound.kind))
            rendered = template.render(compound=parsed.compound,
                DOXYGEN_VERSION=parsed.version,
                FILENAME=parsed.compound.url,
                SEARCHDATA_FORMAT_VERSION=searchdata_format_version,
                # TODO: whitelist only what matters from doxyfile
                **state.doxyfile, **state.config)

            output = os.path.join(html_output, parsed.compound.url)
            with open(output, 'wb') as f:
                f.write(rendered.encode('utf-8'))
                # Add back a trailing newline so we don't need to bother with
                # patching test files to include a trailing newline to make Git
                # happy. Can't use keep_trailing_newline because that'd add it
                # also for nested templates :( The rendered file should never
                # contain a trailing newline on its own.
                assert not rendered.endswith('\n')
                f.write(b'\n')

    # Empty index page in case no mainpage documentation was provided so
    # there's at least some entrypoint. Doxygen version is not set in this
    # case, as this is totally without Doxygen involvement.
    if not os.path.join(xml_input, 'indexpage.xml') in xml_files_metadata:
        logging.debug("writing index.html for an empty mainpage")

        compound = Empty()
        compound.kind = 'page'
        compound.name = state.doxyfile['PROJECT_NAME']
        compound.description = ''
        compound.breadcrumb = [(state.doxyfile['PROJECT_NAME'], 'index.html')]
        template = env.get_template('page.html')
        rendered = template.render(compound=compound,
            DOXYGEN_VERSION=None,
            FILENAME='index.html',
            SEARCHDATA_FORMAT_VERSION=searchdata_format_version,
            # TODO: whitelist only what matters from doxyfile
            **state.doxyfile, **state.config)
        output = os.path.join(html_output, 'index.html')
        with open(output, 'wb') as f:
            f.write(rendered.encode('utf-8'))
            # Add back a trailing newline so we don't need to bother with
            # patching test files to include a trailing newline to make Git
            # happy. Can't use keep_trailing_newline because that'd add it
            # also for nested templates :( The rendered file should never
            # contain a trailing newline on its own.
            assert not rendered.endswith('\n')
            f.write(b'\n')

    if not state.config['SEARCH_DISABLED']:
        logging.debug("building search data for {} symbols".format(len(state.search)))

        data = build_search_data(state, add_lookahead_barriers=search_add_lookahead_barriers, merge_subtrees=search_merge_subtrees, merge_prefixes=search_merge_prefixes)

        if state.config['SEARCH_DOWNLOAD_BINARY']:
            with open(os.path.join(html_output, searchdata_filename.format(search_filename_prefix=state.config['SEARCH_FILENAME_PREFIX'])), 'wb') as f:
                f.write(data)
        else:
            with open(os.path.join(html_output, searchdata_filename_b85.format(search_filename_prefix=state.config['SEARCH_FILENAME_PREFIX'])), 'wb') as f:
                f.write(base85encode_search_data(data))

        # OpenSearch metadata, in case we have the base URL
        if state.config['SEARCH_BASE_URL']:
            logging.debug("writing OpenSearch metadata file")

            template = env.get_template('opensearch.xml')
            # TODO: whitelist only what matters from doxyfile
            rendered = template.render(**state.doxyfile, **state.config)
            output = os.path.join(html_output, 'opensearch.xml')
            with open(output, 'wb') as f:
                f.write(rendered.encode('utf-8'))
                # Add back a trailing newline so we don't need to bother with
                # patching test files to include a trailing newline to make Git
                # happy. Can't use keep_trailing_newline because that'd add it
                # also for nested templates :( The rendered file should never
                # contain a trailing newline on its own.
                assert not rendered.endswith('\n')
                f.write(b'\n')

    # Copy all referenced files
    for i in state.images + state.config['STYLESHEETS'] + state.config['EXTRA_FILES'] + ([state.doxyfile['PROJECT_LOGO']] if state.doxyfile['PROJECT_LOGO'] else []) + ([state.config['FAVICON'][0]] if state.config['FAVICON'] else []) + ([] if state.config['SEARCH_DISABLED'] else ['search.js']):
        # Skip absolute URLs
        if urllib.parse.urlparse(i).netloc:
            logging.debug(f"Ignoring URL file: {i}")
            continue
        logging.debug("Preparing to copy {} to output".format(i))

        # The search.js is special, we encode the version information into its
        # filename
        file_out = search_filename if i == 'search.js' else i

        # If file is found relative to the Doxyfile, use that
        if os.path.exists(os.path.join(state.basedir, i)):
            i = os.path.join(state.basedir, i)
            logging.debug("File found relative to doxyfile at {}".format(i))

        # Otherwise use path relative to script directory
        else:
            i = os.path.join(os.path.dirname(os.path.realpath(__file__)), i)
            logging.debug("File not found relative to doxyfile trying at {}".format(i))

        logging.debug("copying {} to output".format(i))
        shutil.copy(i, os.path.join(html_output, os.path.basename(file_out)))

    # Save updated math cache file
    if not state.config['M_MATH_RENDER_AS_CODE'] and not state.doxyfile['USE_MATHJAX'] and state.config['M_MATH_CACHE_FILE']:
        logging.debug("Pickling latex2svg math cache file: {}".format(math_cache_file))
        latex2svgextra.pickle_cache(math_cache_file)

if __name__ == '__main__': # pragma: no cover
    parser = argparse.ArgumentParser()
    parser.add_argument('config', help="where the Doxyfile or conf.py is")
    parser.add_argument('--templates', help="template directory", default=default_templates)
    parser.add_argument('--wildcard', help="only process files matching the wildcard", default=default_wildcard)
    parser.add_argument('--index-pages', nargs='+', help="index page templates", default=default_index_pages)
    parser.add_argument('--no-doxygen', help="don't run Doxygen before", action='store_true')
    parser.add_argument('--search-no-subtree-merging', help="don't merge search data subtrees", action='store_true')
    parser.add_argument('--search-no-lookahead-barriers', help="don't insert search lookahead barriers", action='store_true')
    parser.add_argument('--search-no-prefix-merging', help="don't merge search result prefixes", action='store_true')
    parser.add_argument('--sort-globbed-files', help="sort globbed files for better reproducibility", action='store_true')
    parser.add_argument('-o', '--output', help='file to save output to')
    parser.add_argument('--debug', help="verbose debug output", action='store_true')
    args = parser.parse_args()

    if args.output is not None:
        if args.debug:
            logging.basicConfig(filename=args.output, filemode='w', level=logging.DEBUG)
        else:
            logging.basicConfig(filename=args.output, filemode='w', level=logging.INFO)

    else:
        if args.debug:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.WARNING)

    config = copy.deepcopy(default_config)

    if args.config.endswith('.py'):
        name, _ = os.path.splitext(os.path.basename(args.config))
        module = SourceFileLoader(name, args.config).load_module()
        if module is not None:
            logging.debug(f"Reading python config from {args.config}")
            config.update((k, v) for k, v in inspect.getmembers(module) if k.isupper())
        doxyfile = os.path.join(os.path.dirname(os.path.abspath(args.config)), config['DOXYFILE'])
    else:
        # Make the Doxyfile path absolute, otherwise everything gets messed up
        doxyfile = os.path.abspath(args.config)

    state = State(config)
    parse_doxyfile(state, doxyfile)

    # Doxygen is stupid and can't create nested directories, create the input
    # directory for it. Don't do it when the argument is empty, because
    # apparently makedirs() is also stupid.
    if state.doxyfile['OUTPUT_DIRECTORY']:
        os.makedirs(state.doxyfile['OUTPUT_DIRECTORY'], exist_ok=True)

    if not args.no_doxygen:
        logging.debug("running Doxygen on {}".format(doxyfile))
        subprocess.run(["doxygen", doxyfile], cwd=os.path.dirname(doxyfile), check=True)

    logging.debug("Template directory: {}".format(args.templates))

    run(state, templates=os.path.abspath(args.templates), wildcard=args.wildcard, index_pages=args.index_pages, search_merge_subtrees=not args.search_no_subtree_merging, search_add_lookahead_barriers=not args.search_no_lookahead_barriers, search_merge_prefixes=not args.search_no_prefix_merging)
