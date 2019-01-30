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
#每次处理的步距
step = 1000
limit_num = 'limit_47'

min_limit = 0
#max_limit = 2000
max_limit = None



if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,
        format='[%(asctime)s %(name)-12s %(levelname)-s] %(message)s',
        datefmt='%m-%d %H:%M:%S',
        filename=time.strftime('1magnetic.log'),
        filemode='a')

    __redis_conn = redis.StrictRedis(host='127.0.0.1', port=52022, password='sany')
    #reset
    #__redis_conn.set(limit_num, 0)

    pydb = pymysql.connect(host='121.196.207.196', port=3306, user='sany', password='kelyn@2017', database='magnetic')
    step = 10
    pydb2 = pymysql.connect(host='127.0.0.1', port=3306, user='sany', password='kelyn@2017', database='magnetic')
    cursor = pydb.cursor()
    cursor2 = pydb2.cursor()

    cur = __redis_conn.get(limit_num) or min_limit
    cur = int(cur)
    logging.info('start: %s'%cur)

    while True:
        # 有max限制
        if max_limit and cur >= max_limit:
            logging.info('end max_limit:%s'%max_limit)
            break
        logging.info('select cur:%s end:%s', cur, cur+step)
        sql = "select id, info_hash, discovered_on, total_size, name from torrents where id >= %s and id< %s;"%(cur, cur+step)
        cursor.execute(sql)
        torrents = cursor.fetchall()

        cur += step
        __redis_conn.set(limit_num, cur)
        if not torrents:
            logging.info('end now, torrents:%s'%torrents)
            break

        for torrent in torrents:
            torrent_id, info_hash, discovered_on, total_size, name = torrent
            if zh_pattern.search(name):
                #print(_id, info_hash, discovered_on, total_size, name )
                pass
            else:
                continue

            #torrent_id 用redis自增解决
            torrent_id = __redis_conn.incr('torrent_id')
            torrent_id = int(torrent_id)
            logging.info('cur torrent_id:%s, info_hash:%s', torrent_id, info_hash)

            __tm_year = time.localtime(discovered_on).tm_year
            cursor.execute("SELECT path, size FROM torrent_files WHERE torrent_id=%s;"%(torrent_id,))
            torrent_files = cursor.fetchall()
            torrent_files = [(torrent_id, size, path) for (path, size) in torrent_files]

            cursor2.execute('insert into torrents (id, info_hash, discovered_on, total_size, name) values(%s, %s, %s, %s, %s)', (torrent_id, info_hash, discovered_on, total_size, name))
            cursor2.executemany("insert into torrent_files_{0} (torrent_id, size, path) values(%s, %s, %s);".format(__tm_year), torrent_files)
        pydb2.commit()

