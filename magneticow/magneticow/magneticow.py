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
import traceback
import time

import re
import appdirs
import flask

from magneticow import utils
from magneticow.authorization import requires_auth, generate_feed_hash
from magneticow import sensitive_filter

File = collections.namedtuple("file", ["path", "size"])
Torrent = collections.namedtuple("torrent", ["info_hash", "name", "size", "discovered_on", "files"])
zh_pattern = re.compile('[^\u4E00-\u9FA5]+')
zh_subtract = re.compile('[<>《》！*(^)$%~!@#$…&%￥—+=、。，；‘’“”：·`]+')
zh_subtract2= re.compile('[^\u4E00-\u9FA5a-zA-Z0-9]+')

gfw = sensitive_filter.DFAFilter()
gfw.parse("./magneticow/data/色情类.txt", ',')
gfw.parse("./magneticow/data/政治类.txt", ',')
gfw.parse("./magneticow/data/dirty.txt", ',')

app = flask.Flask(__name__)
app.config.from_object(__name__)

# TODO: We should have been able to use flask.g but it does NOT persist across different requests so we resort back to
# this. Investigate the cause and fix it (I suspect of Gevent).
magneticod_mysql = None
magneticod_redis = None
mysql_cnf = None

@app.route("/")
@app.route("/search")
@requires_auth
def home_page():
    global magneticod_mysql, magneticod_redis, mysql_cnf
    _lr = flask.request.args.get("lr", 'zh')

    with magneticod_mysql:
        #缓存 homepage torrents 总行数
        torrent_id= magneticod_redis.get('torrent_id') or 0
        torrent_id = int(torrent_id)

        if not torrent_id:
            # COUNT(ROWID) is much more inefficient since it scans the whole table, so use MAX(ROWID)
            try:
                cur = magneticod_mysql.cursor()

                for __lr in ('zh', 'en'):
                    cur = self.__db_conn.cursor()
                    cur.execute('SELECT MAX(`id`) from {0}_torrents;'.format(__lr))
                    res = cur.fetchone()
                    if res and torrent_id < res[0]:
                        torrent_id = res[0] 

                cur.close()
            except (AttributeError, MySQLdb.OperationalError):
                logging.error('mysql connection err, try reconnect:%s', traceback.format_exc())
                magneticod_mysql = MySQLdb.connect(host=mysql_cnf['host'], port=mysql_cnf['port'], user=mysql_cnf['user'], passwd=mysql_cnf['passwd'], db=mysql_cnf['db'], charset='utf8')
                torrent_id = 0

            magneticod_redis.setnx('torrent_id', torrent_id)

        hot_key = 'hot_tag:%s'%(time.strftime('%W'))
        hot_tags = magneticod_redis.zrevrange(hot_key, 0, 15)
        hot_tags = [tag.decode('utf-8') for tag in hot_tags]

    return flask.render_template("homepage.html", n_torrents=torrent_id, hot_tag=hot_tags, _lr=_lr)

@app.route("/torrents/")
@requires_auth
def torrents():
    global magneticod_mysql, magneticod_redis, mysql_cnf
    search = flask.request.args.get("search")
    page = int(flask.request.args.get("page", 0))
    _lr = flask.request.args.get("lr", 'zh')

    #防域名屏蔽
    '''
    if 'tomatow.top' in flask.request.url:
        return flask.redirect("http://47.98.177.0:5001/torrents?search=%s&page=%s"%(search, page), 301)
    '''

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

    SQL_query = "SELECT info_hash, name, total_size, discovered_on FROM `{0}_torrents` ".format(_lr)
    if search:
        key_word = search.split()
        if len(key_word) > 1:
            instr_search = ' and '.join(["instr(`name`, '%s')>1"%(key) for key in key_word])
            SQL_query += "WHERE {0} ".format(instr_search)
        else:
            SQL_query += "WHERE instr(`name`, '{0}')>1 ".format(search)

    if sort_by:
        SQL_query += "ORDER BY {0} LIMIT {1}, 20 ".format(sort_by + ", " + "`id` DESC", 20 * page)
    else:
        SQL_query += "ORDER BY {0} LIMIT {1}, 20 ".format("`id` DESC", 20 * page)

    with magneticod_mysql:
        try:
            cur = magneticod_mysql.cursor()
            cur.execute(SQL_query)
            context["torrents"] = [Torrent(t[0], gfw.filter(t[1]), utils.to_human_size(t[2]),
                                           datetime.fromtimestamp(t[3]).strftime("%d/%m/%Y"), [])
                                   for t in cur.fetchall()]
            
        except (AttributeError, MySQLdb.OperationalError):
            logging.error('mysql connection err, try reconnect:%s', traceback.format_exc())
            magneticod_mysql = MySQLdb.connect(host=mysql_cnf['host'], port=mysql_cnf['port'], user=mysql_cnf['user'], passwd=mysql_cnf['passwd'], db=mysql_cnf['db'], charset='utf8')
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

    # 去掉特殊字符
    search_sub = zh_subtract2.sub(r'', search)
    if search_sub and (len(search_sub)>4 or len(zh_pattern.sub(r'', search))>2 ):
        hot_key = 'hot_tag:%s'%(time.strftime('%W'))
        magneticod_redis.zincrby(hot_key, search_sub)
        #3天
        magneticod_redis.expire(hot_key, 259200)

    context["_lr"] = _lr 
    return flask.render_template("torrents.html", **context)


@app.route("/torrents/<info_hash>/", defaults={"name": None})
@requires_auth
def torrent_redirect(**kwargs):
    global magneticod_mysql, magneticod_redis, mysql_cnf

    _lr = flask.request.args.get("lr", 'zh')
    try:
        info_hash = kwargs["info_hash"]
        assert len(info_hash) == 20
    except (AssertionError, ValueError):  # In case info_hash variable is not a proper hex-encoded bytes
        return flask.abort(400)

    #防域名屏蔽

    with magneticod_mysql:
        try:
            cur = magneticod_mysql.cursor()
            cur.execute("SELECT name FROM {0}_torrents WHERE info_hash='{1}' LIMIT 1;".format(_lr, info_hash,))
        except (AttributeError, MySQLdb.OperationalError):
            logging.error('mysql connection err, try reconnect:%s', traceback.format_exc())
            magneticod_mysql = MySQLdb.connect(host=mysql_cnf['host'], port=mysql_cnf['port'], user=mysql_cnf['user'], passwd=mysql_cnf['passwd'], db=mysql_cnf['db'], charset='utf8')
            return flask.abort(404)

        try:
            name = cur.fetchone()[0]
            name = gfw.filter(name)
        except TypeError:  # In case no results returned, TypeError will be raised when we try to subscript None object
            return flask.abort(404)

    return flask.redirect("/torrents/%s/%s?lr=%s" % (kwargs["info_hash"], name, lr), code=301)


@app.route("/torrents/<info_hash>/<name>")
@requires_auth
def torrent(**kwargs):
    global magneticod_mysql, magneticod_redis, mysql_cnf
    context = {}

    _lr = flask.request.args.get("lr", 'zh')
    try:
        info_hash = kwargs["info_hash"]
        assert len(info_hash) == 40
        name = kwargs["name"]
    except (AssertionError, ValueError):  # In case info_hash variable is not a proper hex-encoded bytes
        return flask.abort(400)

    #防域名屏蔽

    with magneticod_mysql:
        try:
            cur = magneticod_mysql.cursor()
            cur.execute("SELECT id, name, discovered_on FROM %s_torrents WHERE info_hash='%s' LIMIT 1;"%(_lr, info_hash,))
        except (AttributeError, MySQLdb.OperationalError):
            logging.error('mysql connection err, try reconnect:%s', traceback.format_exc())
            magneticod_mysql = MySQLdb.connect(host=mysql_cnf['host'], port=mysql_cnf['port'], user=mysql_cnf['user'], passwd=mysql_cnf['passwd'], db=mysql_cnf['db'], charset='utf8')
            return flask.abort(404)
        try:
            torrent_id, name, discovered_on = cur.fetchone()
            name = gfw.filter(name)
        except TypeError:  # In case no results returned, TypeError will be raised when we try to subscript None object
            return flask.abort(404)

        try:
            __tm_year = time.localtime(discovered_on).tm_year
            cur.execute("SELECT path, size FROM %s_torrent_files_%s WHERE torrent_id=%s;"%(_lr, __tm_year, torrent_id,))
            raw_files = cur.fetchall()
        except (AttributeError, MySQLdb.OperationalError):
            logging.error('mysql connection err, try reconnect:%s', traceback.format_exc())
            magneticod_mysql = MySQLdb.connect(host=mysql_cnf['host'], port=mysql_cnf['port'], user=mysql_cnf['user'], passwd=mysql_cnf['passwd'], db=mysql_cnf['db'], charset='utf8')
            return flask.abort(404)

        size = sum(f[1] for f in raw_files)
        #files = [File(gfw.filter(f[0]), utils.to_human_size(f[1])) for f in raw_files]
        files = []
        for f in raw_files:
            if '_____padding_file_' in  f[0]:
                continue
            gftf = File(gfw.filter(f[0]), utils.to_human_size(f[1]))
            files.append(gftf)

    context["torrent"] = Torrent(info_hash, name, utils.to_human_size(size), datetime.fromtimestamp(discovered_on).strftime("%d/%m/%Y"), files)
    context["_lr"] = _lr
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
        cur.execute("""
            SELECT day, MAX(Lcount)+MAX(Rcount) FROM (
                SELECT FROM_UNIXTIME(discovered_on, '{0}') AS day, count(`id`) as Lcount, 0 as Rcount FROM en_torrents WHERE discovered_on >= {1} GROUP BY day
                UNION ALL
                SELECT FROM_UNIXTIME(discovered_on, '{0}') AS day, 0 as Lcount, count(`id`) as Rcount FROM zh_torrents WHERE discovered_on >= {1} GROUP BY day
                ) AS both_torrent GROUP BY day ORDER BY day
                """.format('%Y-%m-%d', latest_today - 30 * 24 * 60 * 60, ))
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
    _lr = flask.request.args.get("lr", 'zh')
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
                SELECT name, info_hash FROM {0}_torrents where instr(name, {1})>1 ORDER BY id DESC LIMIT 50;
                '''.format(_lr, filter_, )
            )
            context["items"] = [{"title": r[0], "info_hash": r[1]} for r in cur]
    else:
        context["title"] = "The Newest Torrents - magneticow"
        with magneticod_mysql:
            cur = magneticod_mysql.cursor()
            cur.execute('SELECT name, info_hash FROM {0}_torrents ORDER BY `id` DESC LIMIT 50;'.format(_lr))
            context["items"] = [{"title": r[0], "info_hash": r[1]} for r in cur]

    return flask.render_template("feed.xml", **context), 200, {"Content-Type": "application/rss+xml; charset=utf-8"}


def initialize_magneticod_db(mysql_cfg, redis_cfg) -> None:
    global magneticod_mysql, magneticod_redis, mysql_cnf

    logging.info("Connecting to magneticod's database...")

    if not mysql_cfg['host'] or not mysql_cfg['port'] or not mysql_cfg['user'] or not mysql_cfg['passwd'] or not mysql_cfg['db']:
        logging.error('Database init fail, args host:%s, port:%s, user:%s, pwd:%s, db:%s', 
                mysql_cfg['host'], mysql_cfg['port'], mysql_cfg['user'], mysql_cfg['passwd'], mysql_cfg['db'])
        raise Exception('Database init fail')

    magneticod_mysql = MySQLdb.connect(host=mysql_cfg['host'], port=mysql_cfg['port'], user=mysql_cfg['user'], passwd=mysql_cfg['passwd'], db=mysql_cfg['db'], charset='utf8')
    mysql_cnf = mysql_cfg

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
