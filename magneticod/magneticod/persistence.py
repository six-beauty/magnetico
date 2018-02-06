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
import logging
import MySQLdb
import time
import typing
import os
import redis
import traceback

from magneticod import bencode

from .constants import PENDING_INFO_HASHES

def gen_tb_timestamp():
    return time.strftime('%Y%m', time.localtime())

class Database:
    def __init__(self, mysql_cfg, redis_cfg) -> None:
        if not mysql_cfg['host'] or not mysql_cfg['port'] or not mysql_cfg['user'] or not mysql_cfg['passwd'] or not mysql_cfg['db']:
            logging.error('Database init fail, args host:%s, port:%s, user:%s, pwd:%s, db:%s', 
                    mysql_cfg['host'], mysql_cfg['port'], mysql_cfg['user'], mysql_cfg['passwd'], mysql_cfg['db'])
            raise Exception('Database init fail')

        self.__db_conn = self.__db_connect(mysql_cfg['host'], mysql_cfg['port'], mysql_cfg['user'], mysql_cfg['passwd'], mysql_cfg['db'])

        self.__redis_conn = self.__redis_connect(redis_cfg['host'], redis_cfg['port'], redis_cfg['passwd'])

        # We buffer metadata to flush many entries at once, for performance reasons.
        # list of tuple (info_hash, name, total_size, discovered_on)
        self.__pending_metadata = []  # type: typing.List[typing.Tuple[bytes, str, int, int]]
        # list of tuple (info_hash, size, path)
        self.__pending_files = []  # type: typing.List[typing.Tuple[bytes, int, bytes]]

    @staticmethod
    def __db_connect(mysql_host, mysql_port, mysql_user, mysql_pwd, mysql_db) -> MySQLdb.Connection:
        db_conn = MySQLdb.connect(host=mysql_host,port=mysql_port,user=mysql_user,passwd=mysql_pwd,db=mysql_db,charset="utf8")

        with db_conn:
            db_cur = db_conn.cursor()
            db_cur.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS `torrents` (
                        `id` INT(11) NOT NULL AUTO_INCREMENT,
                        `info_hash` VARCHAR(64) NOT NULL COLLATE 'utf8mb4_unicode_ci',
                        `discovered_on` INT(11) NOT NULL DEFAULT '0',
                        `total_size` BIGINT(20) NOT NULL DEFAULT '0',
                        `name` TEXT NOT NULL COLLATE 'utf8mb4_unicode_ci',
                        PRIMARY KEY (`id`),
                        UNIQUE INDEX `info_hash` (`info_hash`),
                        INDEX `discovered_on_index` (`discovered_on`)
                        )COLLATE='utf8mb4_unicode_ci' ENGINE=InnoDB;
                    '''
                    )

            db_cur.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS `torrent_files` (
                        `id` INT(11) NOT NULL AUTO_INCREMENT,
                        `torrent_id` INT(11) NOT NULL DEFAULT '0',
                        `size` BIGINT(20) NOT NULL,
                        `path` TEXT NOT NULL COLLATE 'utf8mb4_unicode_ci',
                        PRIMARY KEY (`id`),
                        INDEX `torrent_id_index` (`torrent_id`)
                        )COLLATE='utf8mb4_unicode_ci' ENGINE=InnoDB;
                    '''
                    )
            db_conn.commit()

        return db_conn

    def __redis_connect(self, redis_host, redis_port, password):
        redis_conn = redis.StrictRedis(host=redis_host, port=redis_port, password=password)

        #redis get torrent_id
        torrent_init = redis_conn.exists('torrent_id')
        if torrent_init == 0:
            #redis数据可能被清空，从数据库读出，重新写入
            cur = self.__db_conn.cursor()
            cur.execute('SELECT id from torrents order by id desc limit 1;')
            res = cur.fetchone()
            if res:
                torrent_id = res[0] 
                #set redis torrent_id
                redis_conn.set('torrent_id', torrent_id)
        return redis_conn

    def add_metadata(self, info_hash: bytes, metadata: bytes) -> bool:
        files = []
        info_hash = info_hash.hex()
        discovered_on = int(time.time())

        torrent_id = self.__redis_conn.incr('torrent_id')
        torrent_id = int(torrent_id)

        #set redis 缓存
        self.__redis_conn.setex('ih:'+info_hash, 86400, torrent_id)

        try:
            info = bencode.loads(metadata)

            assert b"/" not in info[b"name"]
            name = info[b"name"].decode('utf-8')

            if b"files" in info:  # Multiple File torrent:
                for file in info[b"files"]:
                    assert type(file[b"length"]) is int
                    # Refuse trailing slash in any of the path items
                    assert not any(b"/" in item for item in file[b"path"])
                    path = "/".join(i.decode("utf-8") for i in file[b"path"])
                    files.append((torrent_id, file[b"length"], path))
            else:  # Single File torrent:
                assert type(info[b"length"]) is int
                files.append((torrent_id, info[b"length"], name))
        # TODO: Make sure this catches ALL, AND ONLY operational errors
        except (bencode.BencodeDecodingError, AssertionError, KeyError, AttributeError, UnicodeDecodeError, TypeError):
            logging.error('add_metadata exception, %s', traceback.format_exc())
            return False

        self.__pending_metadata.append((torrent_id, info_hash, sum(f[1] for f in files), discovered_on, name))
        # MYPY BUG: error: Argument 1 to "__iadd__" of "list" has incompatible type List[Tuple[bytes, Any, str]];
        #     expected Iterable[Tuple[bytes, int, bytes]]
        # List is an Iterable man...
        self.__pending_files += files  # type: ignore

        logging.info("Added: `%s`, info_hash:%s", name, info_hash)

        # Automatically check if the buffer is full, and commit to the SQLite database if so.
        if len(self.__pending_metadata) >= PENDING_INFO_HASHES:
            self.__commit_metadata()

        return True

    def is_infohash_new(self, info_hash: bytes):
        info_hash = info_hash.hex()
        if info_hash in [x[1] for x in self.__pending_metadata]:
            return False
        cur = self.__db_conn.cursor()
        try:
            #redis缓存
            hash_id = self.__redis_conn.get('ih:'+info_hash)
            if hash_id:
                return False

            #mysql
            cur.execute("SELECT count(info_hash), id FROM torrents where info_hash = %s;", [info_hash])
            x, torrent_id = cur.fetchone()
            #超时了，重新set 缓存
            self.__redis_conn.setex('ih:'+info_hash, 86400, torrent_id or 1)

            return x == 0
        finally:
            cur.close()

    def __commit_metadata(self) -> None:
        cur = self.__db_conn.cursor()

        # noinspection PyBroadException
        try:
            cur.executemany(
                "INSERT INTO torrents (id, info_hash, total_size, discovered_on, name) VALUES (%s, %s, %s, %s, %s);",
                self.__pending_metadata
            )
            cur.executemany(
                "INSERT INTO torrent_files (torrent_id, size, path) VALUES (%s, %s, %s);",
                self.__pending_files
            )
            cur.execute("COMMIT;")
            logging.info("%d metadata (%d files) are committed to the database.",
                          len(self.__pending_metadata), len(self.__pending_files))
        except:
            cur.execute("ROLLBACK;")
            logging.exception("Could NOT commit metadata to the database! (%d metadata are pending)",
                              len(self.__pending_metadata))
        finally:
            #fail, clear metadata
            self.__pending_metadata.clear()
            self.__pending_files.clear()

            cur.close()

    def close(self) -> None:
        if self.__pending_metadata:
            self.__commit_metadata()
        self.__db_conn.close()
