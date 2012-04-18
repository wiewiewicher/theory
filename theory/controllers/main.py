# theory MPD client
# Copyright (C) 2008  Ryan Roemmich <ralfonso@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
import socket
import random

import formencode.htmlfill

from pylons import request, response, session
from pylons import tmpl_context as c
from pylons.controllers.util import abort
from pylons.controllers.util import redirect
from pylons import url
from pylons import config

from theory.lib.base import BaseController, render
from theory.lib import helpers as h
from theory.model.mpdpool import ConnectionClosed, IncorrectPassword, ProtocolError, NoMPDConnection
from theory.model.albumart import AlbumArt, NoArtError

from theory.model import *

log = logging.getLogger(__name__)

class MainController(BaseController):
    requires_auth = True

    def index(self):
        """ the main page controller! """

        c.debug = request.GET.get('debug', 0)
        c.config = ''
        
        try:
            self.m = g.p.connect()
        except (ProtocolError, ConnectionClosed, NoMPDConnection):
            if g.tc.server is None:
                g.tc = TConfig()
                if g.tc.server is None:
                    c.config = '/config?firsttime=1'
            else:
                c.config = '/config?noconnection=1'
            pass
        except IncorrectPassword:
            abort(401)

        return render('/index.html')

    def artists(self):
        """ the controller for the artists frame """

        try:
            self.m = g.p.connect()
        except (NoMPDConnection, ConnectionClosed):
            return render('/null.html')

        c.artists = self.m.artists()
        return render('./artists.html')

    def albums(self):
        """ controller for the albums frame """

        c.artist = request.GET.get('artist', '').encode('utf-8')
        c.album = request.GET.get('album', '').encode('utf-8')

        try:
            self.m = g.p.connect()
        except (NoMPDConnection, ConnectionClosed):
            return render('/null.html')
        c.albums = self.m.albums(c.artist)

        aa = AlbumArt()
        c.album_imgs = aa.artist_art(c.artist)
        random.shuffle(c.album_imgs)
        return render('/albums.html')

    def tracks(self):
        """ controller for the tracks frame """

        c.artist = request.GET.get('artist', '').encode('utf-8')
        c.album = request.GET.get('album', '').encode('utf-8')
        try:
            self.m = g.p.connect()
        except (NoMPDConnection, ConnectionClosed):
            return render('/null.html')

        c.tracks = self.m.tracks(c.artist, c.album)

        c.artist_safe = h.html.url_escape(c.artist)
        c.album_safe = h.html.url_escape(c.album)

        return render('/tracks.html')
 
    def fetchart(self):
        """ 
        creates an AlbumArt object and attemps to load the image from disk.
        if it doesn't exist, attempt to fetch it from Amazon and save to disk 
        """
            
        artist = request.GET.get('artist', '').encode('utf-8')
        album = request.GET.get('album', '').encode('utf-8')
        response.headers['Content-type'] = 'image/jpeg'

        try:
            aa = AlbumArt()
            aa.album_fetch(artist, album)
            img = aa.disk_path
        except NoArtError:
            response.headers['Content-type'] = 'image/png'
            img = 'theory/public/img/noart.png'


        f = open(img, 'rb')
        data = f.read()
        f.close()
        return data
    
    def config(self, use_htmlfill=True):
        """ controller for the configuration iframe """

        c.firsttime = request.GET.get('firsttime', '0')
        c.noconnection = request.GET.get('noconnection')
        c.error = request.GET.get('error')
        c.type = request.GET.get('type')

        configured_outputs = []

        if c.firsttime == '0':
            try:
                self.m = g.p.connect()
                c.outputs = self.m.outputs()

                for o in c.outputs:
                    if o['outputenabled'] == '1':
                        key = 'enabled'
                    else:
                        key = 'disabled'

                    configured_outputs.append({key: o['outputid']})

            except ConnectionClosed:
                return render('/null.html')

        if use_htmlfill:
            values = formencode.variabledecode.variable_encode({'firsttime': c.firsttime, 'server':g.tc.server,
                                                                'port':g.tc.port,
                                                                'password':g.tc.password,'webpassword':g.tc.webpassword,
                                                                'awskey':g.tc.awskey,'timeout':g.tc.timeout,
                                                                'aws_secret':g.tc.aws_secret,
                                                                'lastfmkey':g.tc.lastfmkey,
                                                                'default_search':g.tc.default_search,
                                                                'outputs': configured_outputs})

            return formencode.htmlfill.render(render("/config.html"), values)
        else:
            return render("/config.html")

    def saveconfig(self):
        """ controller to save the web-based configuration """ 
        try:
            fields = validate_custom(form.ConfigForm(), variable_decode=True)
        except formencode.api.Invalid, e:
            return form.htmlfill(self.config(use_htmlfill=False),  e)


        if fields['action'] == 'save config':
            reloadframes = 'true'
            reloadpage = 'true'

            for k in fields.keys():
                setattr(g.tc, k, fields[k])

            try:
                g.tc.commit_config()
            except:
                redirect(url('/config?error=1&type=save'))

            if len(g.genres) == 0:
                g.get_genres()
        else:
            reloadpage = 'false'
            reloadframes = 'false'

        g.p.recreate()
        self.m = g.p.connect()
        outputs = self.m.outputs()

        if fields['firsttime'] == 0:
            enabled_outputs = [x['enabled'] for x in fields['outputs']]
            for o in outputs:
                if int(o['outputid']) in enabled_outputs:
                    self.m.enableoutput(o['outputid'])
                else:
                    self.m.disableoutput(o['outputid'])
        
        return '<script language="javascript">window.parent.setSearchType(\'%s\');window.parent.hideConfig(%s,%s);document.location.replace(\'/null.html\')</script>'\
                % (g.tc.default_search, reloadframes, reloadpage)

    def stats(self):
        """ controller for the stats widget """

        try:
            self.m = g.p.connect()
        except (NoMPDConnection, ConnectionClosed):
            return render('/null.html')

        c.stats = self.m.stats()
        aa = AlbumArt()
        c.dir_size = aa.dir_size()

        return render('/stats.html')

    def fullscreen(self):
        """ controller for the fullscreen widget """

        return render('/fullscreen.html')

    def randomizer(self):
        action = request.GET.get('action', '')
        c.incex = request.GET.get('incex', 'exclude')
        c.selected_genres = request.GET.getall('genres') 
        c.exclude_live = request.GET.get('excludelive', not bool(len(action)))
        c.quantity = int(request.GET.get('quantity', 50))
        c.genres = sorted(g.genres)

        if action:
            self.m = g.p.connect()
            c.random_tracks = self.m.get_random_tracks(c.incex, c.selected_genres, c.exclude_live, c.quantity)
        return render('/randomizer.html')

    def add_random(self):
        self.m = g.p.connect()
        files = request.POST.getall('file')
        for f in files:
            self.m.add(f.encode('utf-8'))

        c.content = '<script language="javascript">window.parent.frames[\'frmplaylist\'].location.reload();</script>'
        return render('/null.html')

    def search(self):
        searchtype = request.GET.get('searchtype', 'Artist')
        q = request.GET.get('q').encode('utf-8')

        if q and len(q) > 2:
            self.m = g.p.connect()
            results = self.m.search(searchtype, q)

            c.artists = set()
            c.albums = set()
            c.tracks = set()

            search_string = q.lower()

            for r in results:
                if 'artist' in r.keys() and search_string in r['artist'].lower():
                    c.artists.add(r['artist'])

                if 'album' in r.keys() and search_string in r['album'].lower():
                    c.albums.add((r['artist'], r['album']))

                if 'title' in r.keys() and search_string in r['title'].lower():
                    c.tracks.add((r['artist'], r['album'], r['title'], r['file']))

        return render('/search.html')

    def streams(self, use_htmlfill=True, **kwargs):
        c.error = request.GET.get('error', '')
        c.streams = g.tc.streams

        if use_htmlfill:
            return formencode.htmlfill.render(render("/streams.html"), {'name':kwargs.get('name',''),
                                                                       'url':kwargs.get('url', '')})
        else:
            return render("/streams.html")
        return render('/streams.html')

    def savestream(self):
        """ controller to save a stream """
        try:
            fields = validate_custom(form.StreamForm())
        except formencode.api.Invalid, e:
            return form.htmlfill(self.streams(use_htmlfill=False),  e)

        try:
            if fields['oldname']:
                index = self._find_stream_index(g.tc.streams, fields['oldname'])

                if index > -1:
                    del g.tc.streams[index]
                
            g.tc.streams.append([fields['name'], fields['url']])
            g.tc.commit_config()
        except:
            redirect(url('/streams?error=1&type=save'))
        
        redirect(url('/streams'))

    def _find_stream_index(self, streams, name):
        for iter, s in enumerate(streams):
            if s[0] == name:
                return iter

        return -1

    def deletestream(self):
        delete = request.GET.get('delete', '')

        if delete:
            index = self._find_stream_index(g.tc.streams, delete)
            if index > -1:
                del g.tc.streams[index]
                try:
                    g.tc.commit_config()
                except:
                    redirect(url('/streams?error=1&type=save'))

        redirect(url('/streams'))
 
    def filesystem(self):
        self.m = g.p.connect()
        c.path = request.GET.get('path', '/').encode('utf-8')
        c.lsinfo = self.m.lsinfo(c.path)

        c.uppath = '/'.join(c.path.split('/')[:-1])

        return render('/filesystem.html')

    def genre(self):
        c.genre = request.GET.get('genre','')
        self.m = g.p.connect()
        c.tracks = self.m.search('Genre', c.genre)
        return render('/genre.html')

    def genres(self):
        c.genres = sorted(g.genres)
        return render('/genres.html')
