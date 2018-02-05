# magneticod - Autonomous BitTorrent DHT crawler and metadata fetcher.
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
import asyncio
import logging
import logging.handlers
import ipaddress
import textwrap
import urllib.parse
import os
import sys
import typing
import json

import appdirs
import humanfriendly

from .constants import DEFAULT_MAX_METADATA_SIZE
from . import __version__
from . import dht
from . import persistence


def parse_ip_port(netloc: str) -> typing.Optional[typing.Tuple[str, int]]:
    # In case no port supplied
    try:
        return str(ipaddress.ip_address(netloc)), 0
    except ValueError:
        pass

    # In case port supplied
    try:
        parsed = urllib.parse.urlparse("//{}".format(netloc))
        ip = str(ipaddress.ip_address(parsed.hostname))
        port = parsed.port
        if port is None:
            return None
    except ValueError:
        return None

    return ip, port


def parse_size(value: str) -> int:
    try:
        return humanfriendly.parse_size(value)
    except humanfriendly.InvalidSize as e:
        raise argparse.ArgumentTypeError("Invalid argument. {}".format(e))


def parse_cmdline_arguments(args: typing.List[str]) -> typing.Optional[argparse.Namespace]:
    parser = argparse.ArgumentParser(
        description="Autonomous BitTorrent DHT crawler and metadata fetcher.",
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
        "--node-addr", action="store", type=parse_ip_port, required=False, default="0.0.0.0:0",
        help="the address of the (DHT) node magneticod will use"
    )

    parser.add_argument(
        "--max-metadata-size", type=parse_size, default=DEFAULT_MAX_METADATA_SIZE,
        help="Limit metadata size to protect memory overflow. Provide in human friendly format eg. 1 M, 1 GB"
    )

    default_cfg_file = os.path.join(appdirs.user_data_dir("magneticod"), "magn.cfg")
    parser.add_argument(
        "--cfg-file", type=str, default=default_cfg_file,
        help="Path to cfg file (default: {})".format(humanfriendly.format_path(default_cfg_file))
    )
    parser.add_argument(
        '-d', '--debug',
        action="store_const", dest="loglevel", const=logging.DEBUG, default=logging.INFO,
        help="Print debugging information in addition to normal processing.",
    )
    return parser.parse_args(args)

def magn_cfg(cfg_file) -> typing.Optional[dict]:
    #no exists, set default
    if not os.path.isfile(cfg_file):
        cfg = {}
        cfg['mysql'] = {"host":"127.0.0.1", "port":3306, "user":'root', "passwd":'123456', "db":"magnetic"}
        cfg['redis'] = {"host":"127.0.0.1", "port":52021, "passwd":'sany'}
        h_cfg = open(cfg_file, 'w')
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
    # main_task = create_tasks()
    arguments = parse_cmdline_arguments(sys.argv[1:])

    log_dir = '%s/log/magneticod'%os.environ['HOME']
    if not os.path.isdir(log_dir):
        os.makedirs(log_dir)
    logging.basicConfig(level=logging.INFO,
        format='[%(asctime)s %(name)-12s %(levelname)-s] %(message)s',
        datefmt='%m-%d %H:%M:%S',
        #filename=time.strftime('log/dump_analyze.log'),
        filemode='a')
    htimed = logging.handlers.TimedRotatingFileHandler("%s/magneticod.log"%(log_dir), 'D', 1, 0)
    htimed.suffix = "%Y%m%d-%H%M"
    htimed.setLevel(logging.INFO)
    formatter = logging.Formatter('[%(asctime)s %(name)-12s %(levelname)-s] %(message)s', datefmt='%m-%d %H:%M:%S')
    htimed.setFormatter(formatter)
    #day time split log file
    logging.getLogger('').addHandler(htimed)
    logging.info("magneticod v%d.%d.%d started", *__version__)

    cfg_args =magn_cfg(arguments.cfg_file)
    if not cfg_args:
        logging.warning('magn_cfg decode cfg fail')
        return 1

    # use uvloop if it's installed
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        logging.info("uvloop is in use")
    except ImportError:
        if sys.platform not in ["linux", "darwin"]:
            logging.warning("uvloop could not be imported, using the default asyncio implementation")

    # noinspection PyBroadException
    try:
        database = persistence.Database(cfg_args['mysql'], cfg_args['redis'])
    except:
        logging.exception("could NOT connect to the database!")
        return 1

    loop = asyncio.get_event_loop()
    node = dht.SybilNode(database, arguments.max_metadata_size)
    loop.create_task(node.launch(arguments.node_addr))

    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        logging.critical("Keyboard interrupt received! Exiting gracefully...")
    finally:
        loop.run_until_complete(node.shutdown())
        database.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
