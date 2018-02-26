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

import argparse
import logging
import logging.handlers
import sys
import textwrap
import typing
import os
import appdirs
import humanfriendly
import json

import gevent.wsgi

from magneticow import magneticow


def magn_cfg(cfg_file) -> typing.Optional[dict]:
    #no exists, set default
    if not os.path.isfile(cfg_file):
        cfg = {}
        cfg['mysql'] = {"host":"127.0.0.1", "port":3306, "user":'root', "passwd":'123456', "db":"magnetic"}
        cfg['redis'] = {"host":"127.0.0.1", "port":52022, "passwd":'sany'}
        h_cfg = open(cfg_file, 'r')
        h_cfg.write(json.dumps(cfg, sort_keys=True, indent=4))
        h_cfg.close()

    h_cfg = open(cfg_file, 'r')
    cfg_str = h_cfg.read()
    try:
        cfg_info = json.loads(cfg_str)
    except Exception as e:
        logging.error('magn_cfg decode fail, file:%s, err:%s', cfg_file, e)
        return None

    if not 'mysql' in cfg_info or not 'redis' in cfg_info:
        logging.error('magn_cfg cfg err:%s, file:%s', cfg_str, cfg_file)
        return None

    return cfg_info

def main() -> int:
    log_dir = '%s/log/magneticow'%os.environ['HOME']
    #log_dir = '/home/sany/log/magneticow'
    if not os.path.isdir(log_dir):
        os.makedirs(log_dir)
    logging.basicConfig(level=logging.INFO,
        format='[%(asctime)s %(name)-12s %(levelname)-s] %(message)s',
        datefmt='%m-%d %H:%M:%S',
        #filename=time.strftime('log/dump_analyze.log'),
        filemode='a')
    htimed = logging.handlers.TimedRotatingFileHandler("%s/magneticow.log"%(log_dir), 'D', 1, 0)
    htimed.suffix = "%Y%m%d-%H%M"
    htimed.setLevel(logging.INFO)
    formatter = logging.Formatter('[%(asctime)s %(name)-12s %(levelname)-s] %(message)s', datefmt='%m-%d %H:%M:%S')
    htimed.setFormatter(formatter)
    #day time split log file
    logging.getLogger('').addHandler(htimed)
    logging.info("magneticow started")

    arguments = parse_args()
    cfg_args =magn_cfg(arguments.cfg_file)
    if not cfg_args:
        logging.warning('magn_cfg decode cfg fail')
        return 1

    magneticow.app.arguments = arguments
    magneticow.app.logger.addHandler(htimed)

    http_server = gevent.wsgi.WSGIServer((arguments.host, arguments.port), magneticow.app, log=magneticow.app.logger)

    magneticow.initialize_magneticod_db(cfg_args['mysql'], cfg_args['redis'])

    try:
        logging.info("magneticow is ready to serve!")
        http_server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        magneticow.close_db()

    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Lightweight web interface for magnetico.",
        epilog=textwrap.dedent("""\
            Copyright (C) 2017  Mert Bora ALPER <bora@boramalper.org>
            Dedicated to Cemile Binay, in whose hands I thrived.

            This program is free software: you can redistribute it and/or modify it under
            the terms of the GNU Affero General Public License as published by the Free
            Software Foundation, either version 3 of the License, or (at your option) any
            later version.

            This program is distributed in the hope that it will be useful, but WITHOUT ANY
            WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
            PARTICULAR PURPOSE.  See the GNU Affero General Public License for more
            details.

            You should have received a copy of the GNU Affero General Public License along
            with this program.  If not, see <http://www.gnu.org/licenses/>.
        """),
        allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--host", action="store", type=str, required=False, default="",
        help="the host address magneticow web server should listen on"
    )
    parser.add_argument(
        "--port", action="store", type=int, required=True,
        help="the port number magneticow web server should listen on"
    )

    auth_group = parser.add_mutually_exclusive_group(required=True)

    auth_group.add_argument(
        "--no-auth", dest='noauth', action="store_true", default=False,
        help="make the web interface available without authentication"
    )
    auth_group.add_argument(
        "--user", action="append", nargs=2, metavar=("USERNAME", "PASSWORD"), type=str,
        help="the pair(s) of username and password for basic HTTP authentication"
    )

    default_cfg_file = os.path.join(appdirs.user_data_dir("magneticod"), "magn.cfg")
    parser.add_argument(
        "--cfg-file", type=str, default=default_cfg_file,
        help="Path to cfg file (default: {})".format(humanfriendly.format_path(default_cfg_file))
    )

    return parser.parse_args(sys.argv[1:])

if __name__ == "__main__":
    sys.exit(main())
