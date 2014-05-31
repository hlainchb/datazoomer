
from fill import fill
from request import route
from response import HTMLResponse
from utils import id_for
from helpers import form_for, link_to, url_for
from tools import as_actions, unisafe
from html import ul
import helpers, tools
from system import system
import os
import log

class Page:
    def __init__(self,content='',callback=None,css=''):

        self.content  = tools.load_content(content) or content
        self.template = 'default'
        self.callback = callback
        self.css      = css
        self.theme    = system.theme
        self.js       = ''
        self.head     = ''
        self.tail     = ''

    def render(self):

        def handle(tag,*args,**keywords):
            if hasattr(self, tag):
                attr = getattr(self, tag)
                if callable(attr):
                    repl = attr(self, *args, **keywords)
                else:
                    repl = attr
                return fill('<dz:','>', repl, handle)

            if tag in helpers.__dict__ and callable(helpers.__dict__[tag]):
                """call functions in a module or module-like object"""
                helper = helpers.__dict__[tag]
                return fill('<dz:','>', helper(*args, **keywords), handle)

        def set_setting(thing, name):
            if thing=='template':
                self.template = name
            elif thing=='app_title':
                self.app_title = name
            return '<!-- %s set to "%s" -->' % (thing, name)

        def render_snippet(system_snippet, page_snippet):
            return '\n'.join(system_snippet.union(set([page_snippet])))


        DEFAULT_TEMPLATE = os.path.join(system.root,'themes','default','default.html')

        self.content = fill('<dz:set_','>',self.content,set_setting)

        self.js   = render_snippet(system.js, self.js)
        self.css  = render_snippet(system.css, self.css)
        self.head = render_snippet(system.head, self.head)
        self.tail = render_snippet(system.tail, self.tail)

        template_pathname = system.theme_path 
        if template_pathname:
            template_filename = os.path.join(template_pathname, self.template+'.html')
            if not os.path.exists(template_filename):
                if not self.template in ['index','content']:
                    log.logger.warning('template missing (%s)' % (template_filename))
                template_filename = os.path.join(template_pathname, 'default.html')
        self.tpl = template_pathname and tools.load(template_filename) or tools.load(DEFAULT_TEMPLATE)

        content = fill('<dz:','>',self.tpl,handle)
        if self.callback:
            content = fill('{{','}}',content,self.callback)

        return HTMLResponse(content)

def render(content='', items=None):
    """Render some content"""

    if items != None:
        if hasattr(items,'keys'):
            t = content % items
        else:
            t = ''.join(content % item for item in items)

    else:
        t = content
    return t

def page(content='', template='default', callback=None, css=None, js=None, title=None, search=None, actions=None, items=None, head=''):

    def render_search(value):
        if value == None: 
            return ''
        elif value == '':
            clear = '<span class="clear"></span>'
        else:
            clear = '<span class="clear"><a href="%s"><img src="/static/images/remove_filter.png"></a></span>' % ('/'.join([''] + route + ['clear']))
        return '<div class="search">%s</div>' % form_for('<input type="text" class="text_field" id="search_text" name="q" value="%s">%s<input class="search_button" type=submit value="Search">' % (value,clear), method='GET')


    header_layout = """
<table id="title_bar"><tr>
<td id="title_bar_left">
<H1>%(title)s</H1>
</td>
<td id="title_bar_right">
%(actions)s
%(search)s
</td>
</tr></table>

"""
    if len(route)>1:
        breadcrumb = link_to(system.app.title,'/'+system.app.name)
    else:
        breadcrumb = ''

    system.result = page = Page()
    if title or actions:
        page_header = header_layout % dict(title=title or '', search=render_search(search), actions=as_actions(actions))
    else:
        page_header = ''

    page.content = unisafe(page_header) + unisafe(render(unisafe(content), items))
    page.css = css or ''
    page.js = js or ''
    page.callback = callback
    page.template = template
    page.head = head
    return page


