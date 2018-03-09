# magneticow - Lightweight web interface for magnetico.
# Copyright (C) 2017  Mert Bora ALPER <bora@boramalper.org>
# Dedicated to Cemile Binay, in whose hands I thrived.
#
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more
# details.
#
# You should have received a copy of the GNU Affero General Public License along with this program.  If not, see
# <http://www.gnu.org/licenses/>.
import collections
import datetime as dt
from datetime import datetime
import logging
import MySQLdb
import os
import redis

import appdirs
import flask

from magneticow import utils
from magneticow.authorization import requires_auth, generate_feed_hash

File = collections.namedtuple("file", ["path", "size"])
Torrent = collections.namedtuple("torrent", ["info_hash", "name", "size", "discovered_on", "files"])


app = flask.Flask(__name__)
app.config.from_object(__name__)

# TODO: We should have been able to use flask.g but it does NOT persist across different requests so we resort back to
# this. Investigate the cause and fix it (I suspect of Gevent).
magneticod_mysql = None
magneticod_redis = None

@app.route("/")
@requires_auth
def home_page():
    global magneticod_mysql, magneticod_redis
    with magneticod_mysql:
        #缓存 homepage torrents 总行数
        n_torrents = magneticod_redis.get('hp_torrents')

        if not n_torrents:
            # COUNT(ROWID) is much more inefficient since it scans the whole table, so use MAX(ROWID)
            try:
                cur = magneticod_mysql.cursor()
                cur.execute("SELECT MAX(`id`) FROM torrents ;")
                n_torrents = cur.fetchone()[0] or 0
                cur.close()
            except (AttributeError, MySQLdb.OperationalError):
                magneticod_mysql = MySQLdb.connect()
                n_torrents = 0

            #10 mins 刷新一次
            magneticod_redis.setex('hp_torrents', 600, n_torrents)

        #byte to int
        n_torrents = int(n_torrents)
    return flask.render_template("homepage.html", n_torrents=n_torrents)

@app.route("/redpack")
@requires_auth
def red_pack():
    return flask.render_template("redpack.html")


@app.route("/torrents/")
@requires_auth
def torrents():
    global magneticod_mysql, magneticod_redis
    search = flask.request.args.get("search")
    page = int(flask.request.args.get("page", 0))

    #防域名屏蔽
    #if '国产' in search or '学生' in search:
    if 'tomatow.top' in flask.request.url:
        return flask.redirect("http://121.196.207.196:5002/torrents?search=%s&page=%s"%(search, page), 301)

    context = {
        "search": search,
        "page": page
    }

    sort_by = flask.request.args.get("sort_by")
    allowed_sorts = [
        None,
        "name ASC",
        "name DESC",
        "total_size ASC",
        "total_size DESC",
        "discovered_on ASC",
        "discovered_on DESC"
    ]
    if sort_by not in allowed_sorts:
        return flask.Response("Invalid value for `sort_by! (Allowed values are %s)" % (allowed_sorts, ), 400)

    SQL_query = "SELECT info_hash, name, total_size, discovered_on FROM `torrents` "
    if search:
        SQL_query += "WHERE MATCH(`name`) AGAINST('{0}' IN BOOLEAN MODE) ".format(search)

    if sort_by:
        SQL_query += "ORDER BY {0} LIMIT {1}, 20 ".format(sort_by + ", " + "`id` DESC", 20 * page)
    else:
        SQL_query += "ORDER BY {0} LIMIT {1}, 20 ".format("`id` DESC", 20 * page)

    with magneticod_mysql:
        try:
            cur = magneticod_mysql.cursor()
            cur.execute(SQL_query)
            context["torrents"] = [Torrent(t[0], t[1], utils.to_human_size(t[2]),
                                           datetime.fromtimestamp(t[3]).strftime("%d/%m/%Y"), [])
                                   for t in cur.fetchall()]
            
        except (AttributeError, MySQLdb.OperationalError):
            magneticod_mysql = MySQLdb.connect()
            context["torrents"] = []

    if len(context["torrents"]) < 20:
        context["next_page_exists"] = False
    else:
        context["next_page_exists"] = True

    if app.arguments.noauth:
        context["subscription_url"] = "/feed/?filter%s" % search
    else:
        username, password = flask.request.authorization.username, flask.request.authorization.password
        context["subscription_url"] = "/feed?filter=%s&hash=%s" % (
            search, generate_feed_hash(username, password, search))

    if sort_by:
        context["sorted_by"] = sort_by

    return flask.render_template("torrents.html", **context)


@app.route("/torrents/<info_hash>/", defaults={"name": None})
@requires_auth
def torrent_redirect(**kwargs):
    global magneticod_mysql, magneticod_redis
    try:
        info_hash = kwargs["info_hash"]
        assert len(info_hash) == 20
    except (AssertionError, ValueError):  # In case info_hash variable is not a proper hex-encoded bytes
        return flask.abort(400)

    #防域名屏蔽
    if 'tomatow.top' in flask.request.url:
        return flask.redirect("http://121.196.207.196:5002/torrents/%s/"%(info_hash), 301)

    with magneticod_mysql:
        try:
            cur = magneticod_mysql.cursor()
            cur.execute("SELECT name FROM torrents WHERE info_hash='%s' LIMIT 1;"%(info_hash,))
        except (AttributeError, MySQLdb.OperationalError):
            magneticod_mysql = MySQLdb.connect()
            return flask.abort(404)

        try:
            name = cur.fetchone()[0]
        except TypeError:  # In case no results returned, TypeError will be raised when we try to subscript None object
            return flask.abort(404)

    return flask.redirect("/torrents/%s/%s" % (kwargs["info_hash"], name), code=301)


@app.route("/torrents/<info_hash>/<name>")
@requires_auth
def torrent(**kwargs):
    global magneticod_mysql, magneticod_redis
    context = {}

    try:
        info_hash = kwargs["info_hash"]
        assert len(info_hash) == 40
        name = kwargs["name"]
    except (AssertionError, ValueError):  # In case info_hash variable is not a proper hex-encoded bytes
        return flask.abort(400)

    #防域名屏蔽
    if 'tomatow.top' in flask.request.url:
        return flask.redirect("http://121.196.207.196:5002/torrents/%s/%s/"%(info_hash, name), 301)

    with magneticod_mysql:
        try:
            cur = magneticod_mysql.cursor()
            cur.execute("SELECT id, name, discovered_on FROM torrents WHERE info_hash='%s' LIMIT 1;"%(info_hash,))
        except (AttributeError, MySQLdb.OperationalError):
            magneticod_mysql = MySQLdb.connect()
            return flask.abort(404)
        try:
            torrent_id, name, discovered_on = cur.fetchone()
        except TypeError:  # In case no results returned, TypeError will be raised when we try to subscript None object
            return flask.abort(404)

        try:
            cur.execute("SELECT path, size FROM torrent_files WHERE torrent_id=%s;"%(torrent_id,))
            raw_files = cur.fetchall()
        except (AttributeError, MySQLdb.OperationalError):
            magneticod_mysql = MySQLdb.connect()
            return flask.abort(404)

        size = sum(f[1] for f in raw_files)
        files = [File(f[0], utils.to_human_size(f[1])) for f in raw_files]

    context["torrent"] = Torrent(info_hash, name, utils.to_human_size(size), datetime.fromtimestamp(discovered_on).strftime("%d/%m/%Y"), files)

    return flask.render_template("torrent.html", **context)


@app.route("/statistics")
@requires_auth
def statistics():
    # Ahhh...
    # Time is hard, really. magneticod used time.time() to save when a torrent is discovered, unaware that none of the
    # specifications say anything about the timezones (or their irrelevance to the UNIX time) and about leap seconds in
    # a year.
    # Nevertheless, we still use it. In future, before v1.0.0, we may change it as we wish, offering a migration
    # solution for the current users. But in the meanwhile, be aware that all your calculations will be a bit lousy,
    # though within tolerable limits for a torrent search engine.

    global magneticod_mysql, magneticod_redis
    with magneticod_mysql:
        # latest_today is the latest UNIX timestamp of today, the very last second.
        latest_today = int((dt.date.today() + dt.timedelta(days=1) - dt.timedelta(seconds=1)).strftime("%s"))
        # Retrieve all the torrents discovered in the past 30 days (30 days * 24 hours * 60 minutes * 60 seconds...)
        # Also, see http://www.sqlite.org/lang_datefunc.html for details of `date()`.
        #     Function          Equivalent strftime()
        #     date(...) 		strftime('%Y-%m-%d', ...)
        cur = magneticod_mysql.cursor()
        cur.execute("SELECT FROM_UNIXTIME(discovered_on, '{0}') AS day, count(`id`) FROM torrents WHERE discovered_on >= {1} GROUP BY day;".format('%Y-%m-%d', latest_today - 7 * 24 * 60 * 60, ))
        results = cur.fetchall()  # for instance, [('2017-04-01', 17428), ('2017-04-02', 28342)]

    return flask.render_template("statistics.html", **{
        # We directly substitute them in the JavaScript code.
        "dates": str([t[0] for t in results]),
        "amounts": str([t[1] for t in results])
    })


@app.route("/feed")
def feed():
    global magneticod_mysql, magneticod_redis
    filter_ = flask.request.args["filter"]
    # Check for all possible users who might be requesting.
    # pylint disabled: because we do monkey-patch! [in magneticow.__main__.py:main()]
    if not app.arguments.noauth:
        hash_ = flask.request.args["hash"]
        for username, password in app.arguments.user:  # pylint: disable=maybe-no-member
            if generate_feed_hash(username, password, filter_) == hash_:
                break
        else:
            return flask.Response(
                "Could not verify your access level for that URL (wrong hash).\n",
                401
            )

    context = {}

    if filter_:
        context["title"] = "`%s` - magneticow" % (filter_,)
        with magneticod_mysql:
            cur = magneticod_mysql.cursor()
            cur.execute(
                '''
                SELECT name, info_hash FROM torrents where match(`name`) against('{0}' in boolean mode) ORDER BY id DESC LIMIT 50;
                '''.format(filter_, )
            )
            context["items"] = [{"title": r[0], "info_hash": r[1]} for r in cur]
    else:
        context["title"] = "The Newest Torrents - magneticow"
        with magneticod_mysql:
            cur = magneticod_mysql.cursor()
            cur.execute('SELECT name, info_hash FROM torrents ORDER BY `id` DESC LIMIT 50;')
            context["items"] = [{"title": r[0], "info_hash": r[1]} for r in cur]

    return flask.render_template("feed.xml", **context), 200, {"Content-Type": "application/rss+xml; charset=utf-8"}


def initialize_magneticod_db(mysql_cfg, redis_cfg) -> None:
    global magneticod_mysql, magneticod_redis

    logging.info("Connecting to magneticod's database...")

    if not mysql_cfg['host'] or not mysql_cfg['port'] or not mysql_cfg['user'] or not mysql_cfg['passwd'] or not mysql_cfg['db']:
        logging.error('Database init fail, args host:%s, port:%s, user:%s, pwd:%s, db:%s', 
                mysql_cfg['host'], mysql_cfg['port'], mysql_cfg['user'], mysql_cfg['passwd'], mysql_cfg['db'])
        raise Exception('Database init fail')

    magneticod_mysql = MySQLdb.connect(host=mysql_cfg['host'], port=mysql_cfg['port'], user=mysql_cfg['user'], passwd=mysql_cfg['passwd'], db=mysql_cfg['db'], charset='utf8')

    logging.info("Preparing for the full-text search (this might take a while)...")
    '''
    with magneticod_mysql:

        magneticod_mysql.execute("CREATE VIRTUAL TABLE temp.fts_torrents USING fts4(name);")
        magneticod_mysql.execute("INSERT INTO fts_torrents (docid, name) SELECT id, name FROM torrents;")
        magneticod_mysql.execute("INSERT INTO fts_torrents (fts_torrents) VALUES ('optimize');")

        magneticod_mysql.execute("CREATE TEMPORARY TRIGGER on_torrents_insert AFTER INSERT ON torrents FOR EACH ROW BEGIN"
                              "    INSERT INTO fts_torrents (docid, name) VALUES (NEW.id, NEW.name);"
                              "END;")
    magneticod_mysql.create_function("rank", 1, utils.rank)
    '''

    magneticod_redis = redis.StrictRedis(host=redis_cfg['host'], port=redis_cfg['port'], password=redis_cfg['passwd'])
    magneticod_redis.time()


def close_db() -> None:
    logging.info("Closing magneticod database...")
    if magneticod_mysql is not None:
        magneticod_mysql.close()
