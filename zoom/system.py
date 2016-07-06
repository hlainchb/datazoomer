
import cgi
import os
import re
import time
import sys
import timeit

import database
import db
from request import request
import config as cfg
from users import UserStore
import session
import settings

from utils import OrderedSet
from instance import Instance

env = os.environ

POSITIVE = ['1','yes',True]
NEGATIVE = ['0', 'False', 'false', 'off', 'no', False]

def existing(path, subdir=None):
    """Returns existing directories only"""
    pathname = path and subdir and os.path.join(os.path.abspath(path), subdir) or path and os.path.abspath(path)
    if pathname and os.path.exists(pathname):
        return pathname


class NoApp(object):
    name  = 'noapp'
    dir = ''
    keywords = ''
    description = ''
    title = name
    theme = ''

class Site(object):
    def __init__(self,**k):
        self.__dict__ = k


class SystemTimer(object):
    def __init__(self, start_time=None):
        self.start_time = start_time or timeit.default_timer()
        self.previous_time = self.start_time
        self.record = []
        self.add('modules loaded')

    def add(self, comment):
        current_time = timeit.default_timer()
        self.record.append('  {} {}: {:6.1f} ms  {:6.1f} ms'.format(
            comment, 
            '.' * (40 - len(comment)),
            (current_time - self.previous_time) * 1000,
            (current_time - self.start_time) * 1000,
        ))
        self.previous_time = current_time

    def report(self):
        self.add('finished')
        title = """
  Steps Completed                              Time      Total
 ------------------------------------------- ---------  ---------
"""
        return title + '\n'.join(self.record) + '\n'


class System(object):

    elapsed_time = property(lambda a: timeit.default_timer() - a.start_time)

    def __getattr__(self,name):
        if name in ['config']:
            path = os.path.abspath(os.path.join(os.path.split(__file__)[0],'../..'))
            self.setup(path)
            if name in self.__dict__ or name in self.__class__.__dict__:
                return getattr(self,name)
            else:
                raise AttributeError

    def release(self):
        self.db.close()
        self.database.close()

    def setup(self,
              instance_path=None,
              server=request.server,
              timer=SystemTimer(timeit.default_timer())):

        if instance_path == None:
            instance_path = Instance('system').path

        self.debugging = True
        self.timer = timer
        self.start_time = timer.start_time
        self.lib_path = os.path.split(os.path.abspath(__file__))[0]

        if not os.path.exists(os.path.join(instance_path, 'dz.conf')):
            raise Exception('instance missing %s' % os.path.abspath(instance_path))
        self.instance_path = os.path.abspath(instance_path)

        if '.' not in sys.path:
            sys.path.insert(0, '.')

        # system config file
        self.config = config = cfg.Config(instance_path, server)

        # connect to the database and stores
        db_engine = config.get('database','engine','mysql')
        db_host   = config.get('database','dbhost','database')
        db_name   = config.get('database','dbname','zoomdev')
        db_user   = config.get('database','dbuser','testuser')
        db_pass   = config.get('database','dbpass','password')

        # legacy database module
        self.database = database.database(
                db_engine,
                db_host,
                db_name,
                db_user,
                db_pass,
                )

        # database module
        db_params = dict(
                engine = db_engine,
                host = db_host,
                db = db_name,
                user = db_user,
                )
        if db_pass:
            db_params['passwd'] = db_pass
        self.db = db.database(**db_params)

        self.db_debug = config.get('database','debug','0') not in NEGATIVE 
        self.db.debug = self.db_debug
        self.database.debug = self.db_debug

        # message queues
        from queues import Queues
        self.queues = Queues(self.db)

        from store import EntityStore
        settings_store = EntityStore(self.database, settings.SystemSettings)
        self.settings = settings.Settings(settings_store, config, 'system')

        if not os.path.exists(config.sites_path):
            raise Exception('sites missing %s' % config.sites_path)

        self.debugging = config.get('errors','debugging','0') == '1'

        self.request = request
        self.server = server
        self.server_name = server # deprecated

        # get current site directory
        self.root = request.instance
        self.uri         = config.get('site','uri','/')
        if self.uri[-1]=='/':
            self.uri = self.uri[:-1]

        # get site info
        self.site = Site(
            name = '',
            theme = '',
            home = os.path.join(config.sites_path, server),
            data_path = os.path.join(config.sites_path, server, config.get('data','path','data')),
            url = self.uri,
            tracking_id = config.get('site', 'tracking_id', ''),
            )

        # authentication
        self.authentication = config.get('site','authentication','basic')
        if self.authentication == 'windows':
            self.nt_username = env.get('REMOTE_USER', None)

        # csrf validation
        self.csrf_validation = config.get('site', 'csrf_validation', True) not in ['0','False','off','no',True]

        # secure cookies
        self.secure_cookies = config.get('sessions', 'secure_cookies', False) not in ['0','False','off','no',False]

        # users and groups
        self.guest = config.get('users', 'default', 'guest')
        self.administrator_group = system.config.get('users', 'administrator_group', 'administrators')
        self.manager_group = config.get('users', 'manager_group', 'managers')
        self.managers = config.get('users', 'managers', 'managers')
        self.developers = config.get('users', 'developers', 'developers')
        self.administrators = config.get('users', 'administrators', 'administrators')

        # apps
        self.index = config.get('apps', 'index', 'index')
        self.home  = config.get('apps', 'home', 'home')

        # background processing
        self.background = config.get('background', 'run', True) not in NEGATIVE

        # users (experimental)
        self.users = UserStore(self.db)

        # email settings
        self.from_addr = system.config.get('mail','from_addr')
        self.mail_delivery = system.config.get('mail', 'delivery', 'immediate')

        # load theme
        self.themes_path = existing(config.get('theme', 'path', os.path.join(self.root,'themes')))
        self.theme = self.themes_path and self.settings.get('theme_name') or config.get('theme','name','default')
        self.set_theme(self.theme)

        self.app = NoApp()
        self.site_name = ''
        self.warnings = []
        self.errors   = []
        self.messages = []

        self.styles   = OrderedSet()
        self.css      = OrderedSet()
        self.libs     = OrderedSet()
        self.js       = OrderedSet()
        self.head     = OrderedSet()
        self.tail     = OrderedSet()

        self.show_errors = config.get('error','users','0') == '1'

        self.profile = config.get('system','profile','0') == '1'

        self.track_visits = config.get('system','track_visits','0').lower() in POSITIVE

        self.webhook = config.get('webhook','url','')

        self.logging = config.get('log', 'logging', True) not in ['0','False','off','no',False]

        self.session = session.Session(self)
        self.session.load_session()


    def set_theme(self, theme_name):

        config = self.config

        # theme
        self.theme = self.themes_path and theme_name
        self.theme_path = existing(self.themes_path, self.theme)
        self.default_theme_path = existing(self.themes_path, 'default')
        self.default_template = self.settings.get('theme_template') or config.get('theme', 'template', 'default')

        # theme templates
        self.template_path = existing(self.theme_path, 'templates')
        self.default_template_path = existing(self.default_theme_path, 'templates')
        self.templates_paths = filter(bool, [
            self.template_path,
            self.default_template_path,
            self.theme_path,
            self.default_theme_path,
            ])
        self.templates = {}


    def setup_test(self):
        # setup config
        path = os.path.join(os.path.dirname(__file__),'../config')
        self.config = config = cfg.Config(path, 'localhost')

        # connect to the database
        self.database = database.database('mysql', 'database', 'test', 'testuser', 'password')
        self.db = db.database('mysql', 'database', 'test', 'testuser', passwd='password')

        # create session
        self.session = session.Session(self)

    def dump(self,name,*items):
        """Prints whatever is passed to it with escaped '<' and '>' characters"""
        for item in items:
            if name in ['request']:
                print name+':', ('%s' % item).replace('<','&lt;').replace('>','&gt;'), '\n%s' % item.__dict__
            else:
                print name+':', ('%s' % item).replace('<','&lt;').replace('>','&gt;')
        print '</pre><hr><pre>'

    def print_status(self):
        dump = self.dump
        dz = self
        print 'DataZoomer System Status<br><hr><pre>'
        for key in self.__dict__:
            dump(key,self.__dict__[key])
        print '</pre>'

    def __str__(self):
        return 'System\n------\n' + '\n'.join('%s%s: %s' % (k, '.'*(25 - len(k)), v) for k,v in self.__dict__.items() if v)

system = System()

if __name__ == '__main__':
    system.setup('../..')


