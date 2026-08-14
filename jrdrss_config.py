# -*- coding: utf-8 -*-
#
# JRSS  Python 3 Jabber RSS transport.
#
# Configuration handling and module-wide constants.
# Kept separate from the core so that db/feed/service modules can import
# the config values without creating circular imports.

import os
import socket
import xml.dom.minidom

programmVersion = "2.0.0"

# Globals filled by load_config():  (for import by other modules)
DB_HOST = "127.0.0.1"
DB_USER = ""
DB_NAME = "jrdrss"
DB_PASS = ""

NAME = "rss.example.com"
HOST = "127.0.0.1"
PORT = "5555"
PASSWORD = ""

ADAPTIVE = "0"
REGALLOW = "1"
ICONLOGO = "0"
SENTSIZE = "3"

admins = []


def find_config():
    override = os.environ.get('JRSS_CONFIG')
    if override:
        return override
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for cand in (
            os.path.join(script_dir, 'config.xml'),
            os.path.abspath(os.path.join(script_dir, '..', 'config.xml'))):
        if os.path.exists(cand):
            return cand
    return os.path.join(script_dir, 'config.xml')


def load_config(path=None):
    global DB_HOST, DB_USER, DB_NAME, DB_PASS
    global NAME, HOST, PORT, PASSWORD
    global ADAPTIVE, REGALLOW, ICONLOGO, SENTSIZE
    global admins

    path = path or find_config()
    dom = xml.dom.minidom.parse(path)

    def gettag(tag, default=None):
        nodes = dom.getElementsByTagName(tag)
        if not nodes or not nodes[0].childNodes:
            return default
        return nodes[0].childNodes[0].data

    DB_HOST = gettag("dbhost", "127.0.0.1")
    DB_USER = gettag("dbuser", "")
    DB_NAME = gettag("dbname", "jrdrss")
    DB_PASS = gettag("dbpass", "")

    NAME = gettag("name", "rss.example.com")
    HOST = gettag("host", "127.0.0.1")
    PORT = gettag("port", "5555")
    PASSWORD = gettag("password", "")

    ADAPTIVE = gettag("adaptive", "0")
    REGALLOW = gettag("regallow", "1")
    ICONLOGO = gettag("iconlogo", "0")
    SENTSIZE = gettag("sentsize", "3")

    admins[:] = [a.childNodes[0].data for a in dom.getElementsByTagName("admin")]


load_config()

# Optional dependencies - only needed for feeding favicon.ico into vCard photo.
# Missing PIL/lxml should not keep the component from running - only the icon.
if int(ICONLOGO):
    try:
        from PIL import Image
        import lxml.html as lh
    except ImportError as e:
        print("Cannot import optional deps for iconlogo:", e)
        Image = None
        lh = None
else:
    Image = None
    lh = None

# timeout for fetching feeds
socket.setdefaulttimeout(10)

rsslogo = 'iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAMAAABEpIrGAAACH1BMVEX3hCL3gyH3hCH2gyH2gh/2gR72gh72gyD4oVf6wpP6vIj5snX4pF33lUL2iSz6u4f+/v7+/Pr+9/L97eD82r36vov4n1P6u4b+/v3////+/f3+8+r817j5rWz2jDD++PT82rz4pmD2hib2giD5snf97d798uj+/Pv+9Oz6xZj3kDj2ii73lD/3mkn5tn37z6j96Nf++vb+/fv827/4nE32hCL2hiX3kjz5r3H82bv+///95tT4o1r2iCv3jDL2iSv2hCP5rGv84cn96tr5tHj84837yqH5s3f3mUn2hyj3kTr6xpr+9/H4m036wY////797+T70a34pV/2hyn5tXv+8un82776wI///v7+9e37zaX3l0X5sHH6xJb6wZD85tL5tXz4qGT70q/83sX97+P6x5v+/fz82Lr2iy/3iy73mUf84Mj++/j97+L3kTv84cr++PP4rGr3jzb98uf85M/3lkL5rW381rX4qmf97d/2hyf4nlH2hif3jjT4qmj4oln5sXP4m0z95dH83MH5sXX6voz3kz796tn84cv5snb3kDn97N73lkP70Kz97N383sT3iy/6u4X++vf5rm75uID+9/D6wI7959T3jzf4nE798un6xZf2gyL++PL70q73jTP948371bP3nE36uoT2ii37yZ785dH2iCn83MD2iS397uD5q2r5uYH2hST4pmH6uYP6uYH5q2n5sXT6uYL4nlKE35UjAAACC0lEQVR42qyRA5cjQRDHr7dqpta2bZuxbZ9t27bNz3rdebGe9p/MTONX3rM7YoyVlboHAJRkBFbMnsorKquqa2qhCMOwrr6+obGpuaW1FokVAtraO4Q6u7p7ehEKeuhIqK9/YHCI5QHDI6ONYwlofGIy10kZTE3PVM/OzS/EicWlZcohVkiWJVxdW99oFMTm1jZAtocdhVKFXFNqzZggtNtZPhjp9M0Go8mMQ2ix2uI+7MgyAUdHh7PB5fZ4Ec0+vyACk0OZQLBDKBSORIlUMUEs7h2EDGBfogv1+wdWSHVAROnypIMwOHjosKthUyBH1CtkPnqMr46foPQ0VYMnT82ePiOIsx7Cc+f54sLFjDwZEOKlysuCuHIV8doFvriuhMxWEA2pbtwUeRhuDZ1o5gv/bUzHGLpzdwoI7o2K9O4jPuDhOitTowd4OPfo8RMvqZ42cCIyiM+eizRTMYamX/ASbC8BX+n5xes3OPiWf99NDyVSRJ8w7Hj/gegjr/DTZxm/8O/X+3ICGPoW78H3H4Q/f/E+//4jDfA6zsSkBIA3/grgnxfo/+YvADIWVrEtkpaUlFgMCwnmJUvlJdOWVSszMi+XkUyTXLGSrXSVgJTENLg32Jes5lzTA0wljGvXrd+wfmMNu/amzRs2b0HkAmCOYFFmBocIKOEwAwWAACyCyHwwBpjJBKGpAgAbEWloKH7cQAAAAABJRU5ErkJggg=='