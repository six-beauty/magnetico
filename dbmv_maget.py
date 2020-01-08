# coding=utf-8
import MySQLdb
import MySQLdb.cursors


def build_tables(lang):
	remote_conn = MySQLdb.connect(host='62.234.98.141',port=3306,user='sany',passwd='kelyn@2017',db='magnetic',charset="utf8")
	remote_cur = remote_conn.cursor()

	remote_cur.execute(
	'''
	CREATE TABLE `%s_torrents` (
	`id` int(11) NOT NULL AUTO_INCREMENT,
	`info_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
	`discovered_on` int(11) NOT NULL DEFAULT '0',
	`total_size` bigint(20) NOT NULL DEFAULT '0',
	`name` text COLLATE utf8mb4_unicode_ci NOT NULL,
	PRIMARY KEY (`id`),
	UNIQUE KEY `info_hash` (`info_hash`),
	KEY `discovered_on_index` (`discovered_on`)
	) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
	'''%lang
	)

	for year in [2018, 2019, 2020]:
		remote_cur.execute(
		'''
		CREATE TABLE `%s_torrent_files_%d` (
		`id` int(11) NOT NULL AUTO_INCREMENT,
		`torrent_id` int(11) NOT NULL DEFAULT '0',
		`size` bigint(20) NOT NULL,
		`path` text COLLATE utf8mb4_unicode_ci NOT NULL,
		PRIMARY KEY (`id`),
		KEY `torrent_id_index` (`torrent_id`)
		) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
		'''%(lang, year)
		)
	remote_conn.commit()


def backup_torrents(lang):
	local_conn = MySQLdb.connect(host='127.0.0.1',port=3306,user='sany',passwd='kelyn@2017',db='magnetic',charset="utf8")
	local_cur = local_conn.cursor()

	remote_conn = MySQLdb.connect(host='62.234.98.141',port=3306,user='sany',passwd='kelyn@2017',db='magnetic',charset="utf8")
	remote_cur = remote_conn.cursor()

	count = 5000
	_id_index = 0
	while True:
		print('lang:', lang, _id_index)
		local_cur.execute('select id, info_hash, discovered_on, total_size, name from %s_torrents order by id limit %d, %d '%(lang, _id_index, count))
		torrents = local_cur.fetchall()
		if not torrents:
			# 没有了
			break

		torrents = ','.join([str(torrent) for torrent in torrents])
		remote_cur.execute("insert into %s_torrents (id, info_hash, discovered_on, total_size, name) values %s ;"%(lang, torrents) )
		remote_conn.commit()

		_id_index = _id_index + count + 1
		

def backup_torrent_files(lang, year):
	local_conn = MySQLdb.connect(host='127.0.0.1',port=3306,user='sany',passwd='kelyn@2017',db='magnetic',charset="utf8")
	local_cur = local_conn.cursor()

	remote_conn = MySQLdb.connect(host='62.234.98.141',port=3306,user='sany',passwd='kelyn@2017',db='magnetic',charset="utf8")
	remote_cur = remote_conn.cursor()

	count = 5000
	_id_index = 0
	while True:
		print('lang2:', lang, _id_index)
		local_cur.execute('select id, torrent_id, size, path from %s_torrent_files_%d order by id limit %d, %d '%(lang, year, _id_index, count))
		torrents = local_cur.fetchall()
		if not torrents:
			# 没有了
			break

		torrents = ','.join([str(torrent) for torrent in torrents])
		remote_cur.execute("insert into %s_torrent_files_%d (id, torrent_id, size, path) values %s ;"%(lang, year, torrents) )
		remote_conn.commit()

		_id_index = _id_index + count + 1


if __name__=='__main__':
	lang = 'en'

	build_tables(lang)

	backup_torrents(lang)

	for year in [2018, 2019, 2020]:
		backup_torrent_files(lang, year)
