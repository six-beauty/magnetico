#!/usr/bin/python3
# coding=utf-8

import pymysql
import redis
import re
import jieba.analyse
import langconv
import sys
import time
import logging

zh_pattern = re.compile('[\u4e00-\u9fa5]+')
#jieba.load_userdict('./extra_dict/word_dict.txt')
jieba.analyse.set_idf_path("./extra_dict/idf.txt.big")
zh_hans = langconv.Converter('zh-hans')


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,
        format='[%(asctime)s %(name)-12s %(levelname)-s] %(message)s',
        datefmt='%m-%d %H:%M:%S',
        filename=time.strftime('1magnetic.log'),
        filemode='a')

    __redis_conn = redis.StrictRedis(host='127.0.0.1', port=52022, password='sany')

    #数据库密码
    passwd = ''
    pydb = pymysql.connect(host='121.196.207.196', port=3306, user='sany', password=passwd, database='magnetic')
    step = 10
    cursor = pydb.cursor()

    sql = "select id, info_hash, discovered_on, total_size, name from torrents where instr(name, '%s');"%('tumblr')
    cursor.execute(sql)
    torrents = cursor.fetchall()

    pydb2 = pymysql.connect(host='127.0.0.1', port=3306, user='sany', password=passwd, database='magnetic')
    cursor2 = pydb2.cursor()

    for torrent in torrents:
        torrent_id, info_hash, discovered_on, total_size, name = torrent
        if zh_pattern.search(name):
            #print(_id, info_hash, discovered_on, total_size, name )
            continue
        else:
            pass

        cursor2.execute("select id, info_hash from zh_torrents where info_hash = '%s';"%info_hash)
        if cursor2.fetchall():
            #数据库已经有了
            continue

        #torrent_id 用redis自增解决
        torrent_id = __redis_conn.incr('torrent_id')
        torrent_id = int(torrent_id)
        logging.info('cur torrent_id:%s, info_hash:%s', torrent_id, info_hash)

        exc = cursor2.execute('insert into zh_torrents (id, info_hash, discovered_on, total_size, name) values(%s, %s, %s, %s, %s)', (torrent_id, info_hash, discovered_on, total_size, name))
        if exc:
            __tm_year = time.localtime(discovered_on).tm_year
            cursor.execute("SELECT path, size FROM torrent_files WHERE torrent_id=%s;"%(torrent_id,))
            torrent_files = cursor.fetchall()
            torrent_files = [(torrent_id, size, path) for (path, size) in torrent_files]

            cursor2.executemany("insert into zh_torrent_files_{0} (torrent_id, size, path) values(%s, %s, %s);".format(__tm_year), torrent_files)
    pydb2.commit()

